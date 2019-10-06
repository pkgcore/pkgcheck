import socket
import urllib.request
from functools import partial
from itertools import chain

from pkgcore.fetch import fetchable
from snakeoil.iterables import partition

from .. import addons, results
from . import NetworkCheck


class _DeadUrlResult(results.FilteredVersionResult, results.Warning):
    """Generic result for a dead URL."""

    def __init__(self, url, message, **kwargs):
        super().__init__(**kwargs)
        self.url = url
        self.message = message

    @property
    def desc(self):
        return f'{self.message}: {self.url}'


class DeadHomepage(_DeadUrlResult):
    """Package with a dead HOMEPAGE."""


class DeadSrcUrl(_DeadUrlResult):
    """Package with a dead SRC_URI target."""


class _RedirectedUrlResult(results.FilteredVersionResult, results.Warning):
    """Generic result for a URL that permanently redirects to a different site."""

    def __init__(self, url, new_url, **kwargs):
        super().__init__(**kwargs)
        self.url = url
        self.new_url = new_url

    @property
    def desc(self):
        return f'permanently redirected: {self.url} -> {self.new_url}'


class RedirectedHomepage(_RedirectedUrlResult):
    """Package with a HOMEPAGE that permanently redirects to a different site."""


class RedirectedSrcUrl(_RedirectedUrlResult):
    """Package with a SRC_URI target that permanently redirects to a different site."""


class SSLCertificateError(results.FilteredVersionResult, results.Warning):
    """Package with https:// HOMEPAGE with an invalid SSL cert."""

    def __init__(self, url, message, **kwargs):
        super().__init__(**kwargs)
        self.url = url
        self.message = message

    @property
    def desc(self):
        return f'SSL cert error: {self.message}: {self.url}'


class HttpsUrlAvailable(results.FilteredVersionResult, results.Warning):
    """URL uses http:// when https:// is available."""

    def __init__(self, http_url, https_url, **kwargs):
        super().__init__(**kwargs)
        self.http_url = http_url
        self.https_url = https_url

    @property
    def desc(self):
        return f'HTTPS url available: {self.http_url} -> {self.https_url}'


class _RequestException(Exception):
    """Wrapper for requests exceptions."""

    def __init__(self, exc, msg=None):
        self.request_exc = exc
        self.msg = msg

    def __str__(self):
        if self.msg:
            return self.msg
        return str(self.request_exc)


class SSLError(_RequestException):
    """Wrapper for requests SSLError exception."""


class RequestError(_RequestException):
    """Wrapper for generic requests exception."""


class _UrlCheck(NetworkCheck):
    """Various URL related checks that require internet access."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dead_result = None
        self.redirected_result = None

    def _http_check(self, url, *, pkg):
        """Check http:// and https:// URLs using requests."""
        result = None
        try:
            r = self.session.get(url)

            redirected_url = None
            for response in r.history:
                if not response.is_permanent_redirect:
                    break
                redirected_url = response.headers['location']
                hsts = 'strict-transport-security' in response.headers

            if redirected_url:
                if redirected_url.startswith('https://') and url.startswith('http://'):
                    result = HttpsUrlAvailable(url, redirected_url, pkg=pkg)
                elif redirected_url.startswith('http://') and hsts:
                    redirected_url = f'https://{redirected_url[7:]}'
                    result = self.redirected_result(url, redirected_url, pkg=pkg)
                else:
                    result = self.redirected_result(url, redirected_url, pkg=pkg)
        except SSLError as e:
            result = SSLCertificateError(url, str(e), pkg=pkg)
        except RequestError as e:
            result = self.dead_result(url, str(e), pkg=pkg)
        return result

    def _https_available_check(self, url, *, future, orig_url, pkg):
        """Check if https:// alternatives exist for http:// URLs."""
        result = None
        try:
            r = self.session.get(url)

            redirected_url = None
            for response in r.history:
                if not response.is_permanent_redirect:
                    break
                redirected_url = response.headers['location']
                hsts = 'strict-transport-security' in response.headers

            # skip result if http:// URL check was redirected to https://
            if not isinstance(future.result(), HttpsUrlAvailable):
                if redirected_url:
                    if redirected_url.startswith('https://'):
                        result = HttpsUrlAvailable(orig_url, redirected_url, pkg=pkg)
                    elif redirected_url.startswith('http://') and hsts:
                        redirected_url = f'https://{redirected_url[7:]}'
                        result = HttpsUrlAvailable(orig_url, redirected_url, pkg=pkg)
                else:
                    result = HttpsUrlAvailable(orig_url, url, pkg=pkg)
        except (RequestError, SSLError) as e:
            pass
        return result

    def _ftp_check(self, url, *, pkg):
        """Check ftp:// URLs using urllib."""
        result = None
        try:
            response = urllib.request.urlopen(url, timeout=self.timeout)
        except urllib.error.URLError as e:
            result = self.dead_result(url, str(e.reason), pkg=pkg)
        except socket.timeout as e:
            result = self.dead_result(url, str(e), pkg=pkg)
        return result

    def task_done(self, results_q, pkg, future):
        result = future.result()
        if result:
            if pkg is not None:
                # recreate result object with different pkg target
                data = result.attrs_to_pkg(result._attrs)
                data['pkg'] = pkg
                result = result.__class__(**data)
            results_q.put([result])

    def _get_urls(self, pkg):
        raise NotImplementedError

    def _schedule_check(self, func, url, executor, futures, results_q, **kwargs):
        future = futures.get(url)
        if future is None:
            future = executor.submit(func, url, **kwargs)
            future.add_done_callback(partial(self.task_done, results_q, None))
            futures[url] = future
        else:
            future.add_done_callback(partial(self.task_done, results_q, kwargs['pkg']))

    def schedule(self, pkg, executor, futures, results_q):
        http_urls, ftp_urls = partition(
            self._get_urls(pkg), predicate=lambda x: x.startswith('ftp://'))
        http_urls = tuple(http_urls)

        for urls, func in ((http_urls, self._http_check),
                           (ftp_urls, self._ftp_check)):
            for url in urls:
                self._schedule_check(func, url, executor, futures, results_q, pkg=pkg)

        http_to_https_urls = (
            (url, f'https://{url[7:]}') for url in http_urls if url.startswith('http://'))
        for orig_url, url in http_to_https_urls:
            future = futures[orig_url]
            self._schedule_check(
                self._https_available_check, url, executor, futures, results_q,
                future=future, orig_url=orig_url, pkg=pkg)


class HomepageUrlCheck(_UrlCheck):
    """Various HOMEPAGE related checks that require internet access."""

    known_results = frozenset([
        DeadHomepage, RedirectedHomepage, HttpsUrlAvailable, SSLCertificateError])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dead_result = DeadHomepage
        self.redirected_result = RedirectedHomepage

    def _get_urls(self, pkg):
        return pkg.homepage


class FetchablesUrlCheck(_UrlCheck):
    """Various SRC_URI related checks that require internet access."""

    known_results = frozenset([
        DeadSrcUrl, RedirectedSrcUrl, HttpsUrlAvailable, SSLCertificateError])
    required_addons = (addons.UseAddon,)

    def __init__(self, *args, use_addon, **kwargs):
        super().__init__(*args, **kwargs)
        self.fetch_filter = use_addon.get_filter('fetchables')
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
