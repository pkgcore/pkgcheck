import concurrent.futures
import urllib.request
import ssl
import threading
from functools import partial
from itertools import chain

from pkgcore.fetch import fetchable
from snakeoil.compatibility import IGNORED_EXCEPTIONS

from .. import addons, base


class DeadHomepage(base.VersionedResult, base.Warning):
    """Package with a dead HOMEPAGE."""

    def __init__(self, url, message, **kwargs):
        super().__init__(**kwargs)
        self.url = url
        self.message = message

    @property
    def desc(self):
        return f'dead homepage, {self.message}: {self.url!r}'


class SSLCertificateError(base.VersionedResult, base.Warning):
    """Package with https:// HOMEPAGE with an invalid SSL cert."""

    def __init__(self, url, message, **kwargs):
        super().__init__(**kwargs)
        self.url = url
        self.message = message

    @property
    def desc(self):
        return f'SSL cert error, {self.message}: {self.url!r}'


class RedirectedHomepage(base.VersionedResult, base.Warning):
    """Package with a HOMEPAGE that redirects to a different site."""

    def __init__(self, url, redirected, **kwargs):
        super().__init__(**kwargs)
        self.url = url
        self.redirected = redirected

    @property
    def desc(self):
        return f'redirected homepage, {self.url!r} -> {self.redirected!r}'


class DeadSrcUrl(base.VersionedResult, base.Warning):
    """Package with a dead SRC_URI target."""

    def __init__(self, url, message, **kwargs):
        super().__init__(**kwargs)
        self.url = url
        self.message = message

    @property
    def desc(self):
        return f'dead SRC_URI target, {self.message}: {self.url!r}'


class _UrlCheck(base.NetworkCheck):
    """Various URL related checks that require internet access."""

    feed_type = base.versioned_feed

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.checked = {}
        self.executor = concurrent.futures.ThreadPoolExecutor()
        self.timeout = self.options.timeout
        self.reporter_lock = threading.Lock()
        self.redirected_result = None
        self.dead_result = None

    def _url_to_result(self, url):
        result = False
        # TODO: support spoofing user agent?
        req = urllib.request.Request(url)
        try:
            response = urllib.request.urlopen(req, timeout=self.timeout)
            if self.redirected_result is not None:
                response_url = response.geturl()
                if response_url != url:
                    result = partial(self.redirected_result, url, response_url)
        except urllib.error.HTTPError as e:
            if e.code >= 400:
                result = partial(self.dead_result, url, str(e))
        except urllib.error.URLError as e:
            result = partial(self.dead_result, url, str(e))
        except ssl.CertificateError as e:
            result = partial(SSLCertificateError, url, str(e))
        except IGNORED_EXCEPTIONS:
            raise
        except Exception as e:
            result = partial(self.dead_result, url, str(e))
        return result

    def _done(self, pkg, future):
        result = future.result()
        if result:
            with self.reporter_lock:
                self.options.reporter.report(result(pkg=pkg))

    def _get_urls(self, pkg):
        raise NotImplementedError

    def feed(self, pkg):
        for url in self._get_urls(pkg):
            future = self.checked.get(url)
            if future is None:
                future = self.executor.submit(self._url_to_result, url)
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

    known_results = (DeadHomepage, RedirectedHomepage, SSLCertificateError)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.redirected_result = RedirectedHomepage
        self.dead_result = DeadHomepage

    def _get_urls(self, pkg):
        return pkg.homepage


class FetchablesUrlCheck(_UrlCheck):
    """Various SRC_URI related checks that require internet access."""

    known_results = (DeadSrcUrl, SSLCertificateError)
    required_addons = (addons.UseAddon,)

    def __init__(self, options, iuse_handler):
        super().__init__(options)
        self.fetch_filter = iuse_handler.get_filter('fetchables')
        self.dead_result = DeadSrcUrl

    def _get_urls(self, pkg):
        # ignore conditionals
        fetchables, _ = self.fetch_filter(
            (fetchable,), pkg,
            pkg._get_attr['fetchables'](
                pkg, allow_missing_checksums=True,
                ignore_unknown_mirrors=True, skip_default_mirrors=True))
        return chain.from_iterable(f.uri for f in fetchables.keys())
