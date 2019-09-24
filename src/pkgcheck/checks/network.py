import concurrent.futures
import urllib.request
import socket
import ssl
import threading
from functools import partial
from itertools import chain

from pkgcore.fetch import fetchable
from snakeoil.compatibility import IGNORED_EXCEPTIONS

from .. import addons, base
from . import NetworkCheck


class _DeadUrlResult(base.FilteredVersionResult, base.Warning):
    """Generic result for a dead URL."""

    def __init__(self, url, message, **kwargs):
        super().__init__(**kwargs)
        self.url = url
        self.message = message

    @property
    def desc(self):
        return f'{self.message}: {self.url!r}'


class DeadHomepage(_DeadUrlResult):
    """Package with a dead HOMEPAGE."""


class DeadSrcUrl(_DeadUrlResult):
    """Package with a dead SRC_URI target."""


class _RedirectedUrlResult(base.FilteredVersionResult, base.Warning):
    """Generic result for a URL that permanently redirects to a different site."""

    def __init__(self, url, new_url, **kwargs):
        super().__init__(**kwargs)
        self.url = url
        self.new_url = new_url

    @property
    def desc(self):
        return f'permanently redirected url, {self.url!r} -> {self.new_url!r}'


class RedirectedHomepage(_RedirectedUrlResult):
    """Package with a HOMEPAGE that permanently redirects to a different site."""


class RedirectedSrcUrl(_RedirectedUrlResult):
    """Package with a SRC_URI target that permanently redirects to a different site."""


class SSLCertificateError(base.FilteredVersionResult, base.Warning):
    """Package with https:// HOMEPAGE with an invalid SSL cert."""

    def __init__(self, url, message, **kwargs):
        super().__init__(**kwargs)
        self.url = url
        self.message = message

    @property
    def desc(self):
        return f'SSL cert error, {self.message}: {self.url!r}'


class HttpsUrlAvailable(base.FilteredVersionResult, base.Warning):
    """URL uses http:// when https:// is available."""

    def __init__(self, http_url, https_url, **kwargs):
        super().__init__(**kwargs)
        self.http_url = http_url
        self.https_url = https_url

    @property
    def desc(self):
        return f'{self.http_url} should use {self.https_url}'


class _HttpRedirected301(Exception):
    """Exception used for flagging HTTP 301 redirects."""

    def __init__(self, url):
        self.url = url


class _FlagHttp301RedirectHandler(urllib.request.HTTPRedirectHandler):
    """Flag HTTP 301 redirects when using urllib."""

    def http_error_301(self, req, fp, code, msg, headers):
        new_url = headers['Location']
        super().http_error_301(req, fp, code, msg, headers)
        raise _HttpRedirected301(new_url)


class _UrlCheck(NetworkCheck):
    """Various URL related checks that require internet access."""

    feed_type = base.versioned_feed

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.checked = {}
        self.executor = concurrent.futures.ThreadPoolExecutor()
        self.timeout = self.options.timeout
        self.reporter_lock = threading.Lock()
        self.dead_result = None
        self.redirected_result = None

        self.url_opener = urllib.request.build_opener(_FlagHttp301RedirectHandler())
        # spoof user agent similar to what would be used when fetching files
        self.url_opener.addheaders = [('User-Agent', 'Wget/1.20.3 (linux-gnu)')]

    def _url_to_result(self, url):
        result = False
        try:
            response = self.url_opener.open(url, timeout=self.timeout)
        except _HttpRedirected301 as e:
            result = partial(self.redirected_result, url, e.url)
        except urllib.error.HTTPError as e:
            if e.code >= 400:
                result = partial(self.dead_result, url, str(e))
        except urllib.error.URLError as e:
            result = partial(self.dead_result, url, str(e))
        except ssl.CertificateError as e:
            result = partial(SSLCertificateError, url, str(e))
        except socket.timeout as e:
            result = partial(self.dead_result, url, str(e))
        return result

    def _https_check(self, url):
        result = False
        try:
            response = self.url_opener.open(url, timeout=self.timeout)
            result = partial(HttpsUrlAvailable, f'http://{url[8:]}', url)
        except IGNORED_EXCEPTIONS:
            raise
        except Exception:
            pass
        return result

    def _done(self, pkg, future):
        result = future.result()
        if result:
            with self.reporter_lock:
                self.options.reporter.report(result(pkg=pkg))

    def _get_urls(self, pkg):
        raise NotImplementedError

    def _http_to_https_urls(self, urls):
        for url in urls:
            if url.startswith('http://'):
                yield f'https://{url[7:]}'

    def feed(self, pkg):
        target_urls = tuple(self._get_urls(pkg))
        for urls, func in ((target_urls, self._url_to_result),
                          (self._http_to_https_urls(target_urls), self._https_check)):
            for url in urls:
                future = self.checked.get(url)
                if future is None:
                    future = self.executor.submit(func, url)
                    future.add_done_callback(partial(self._done, pkg))
                    self.checked[url] = future
                elif future.done():
                    result = future.result()
                    if result:
                        yield result(pkg=pkg)
                else:
                    future.add_done_callback(partial(self._done, pkg))


class HomepageUrlCheck(_UrlCheck):
    """Various HOMEPAGE related checks that require internet access."""

    known_results = (DeadHomepage, RedirectedHomepage, HttpsUrlAvailable, SSLCertificateError)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dead_result = DeadHomepage
        self.redirected_result = RedirectedHomepage

    def _get_urls(self, pkg):
        return pkg.homepage


class FetchablesUrlCheck(_UrlCheck):
    """Various SRC_URI related checks that require internet access."""

    known_results = (DeadSrcUrl, RedirectedSrcUrl, HttpsUrlAvailable, SSLCertificateError)
    required_addons = (addons.UseAddon,)

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.fetch_filter = iuse_handler.get_filter('fetchables')
        self.dead_result = DeadSrcUrl
        self.redirected_result = RedirectedSrcUrl

    def _get_urls(self, pkg):
        # ignore conditionals
        fetchables, _ = self.fetch_filter(
            (fetchable,), pkg,
            pkg._get_attr['fetchables'](
                pkg, allow_missing_checksums=True,
                ignore_unknown_mirrors=True, skip_default_mirrors=True))
        return chain.from_iterable(f.uri for f in fetchables.keys())
