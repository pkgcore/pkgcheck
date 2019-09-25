import concurrent.futures
from multiprocessing import cpu_count
import urllib.request
import socket
import ssl
import threading
from functools import partial
from itertools import chain

from pkgcore.fetch import fetchable
from snakeoil.iterables import partition
from snakeoil.log import suppress_logging

from .. import addons, base
from . import NetworkCheck


try:
    import requests

    class _DeadUrlResult(base.FilteredVersionResult, base.Warning):
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


    class _RedirectedUrlResult(base.FilteredVersionResult, base.Warning):
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


    class SSLCertificateError(base.FilteredVersionResult, base.Warning):
        """Package with https:// HOMEPAGE with an invalid SSL cert."""

        def __init__(self, url, message, **kwargs):
            super().__init__(**kwargs)
            self.url = url
            self.message = message

        @property
        def desc(self):
            return f'SSL cert error: {self.message}: {self.url}'


    class HttpsUrlAvailable(base.FilteredVersionResult, base.Warning):
        """URL uses http:// when https:// is available."""

        def __init__(self, http_url, https_url, **kwargs):
            super().__init__(**kwargs)
            self.http_url = http_url
            self.https_url = https_url

        @property
        def desc(self):
            return f'HTTPS url available: {self.http_url} -> {self.https_url}'


    class _Session(requests.Session):
        """Custom requests session handling timeout, concurrency, and header settings."""

        def __init__(self, concurrent=None, timeout=None):
            super().__init__()
            if timeout == 0:
                # set timeout to 0 to never timeout
                self.timeout = None
            else:
                # default to timing out connections after 5 seconds
                self.timeout = timeout if timeout is not None else 5

            # block when urllib3 connection pool is full
            concurrent = concurrent if concurrent is not None else cpu_count() * 5
            a = requests.adapters.HTTPAdapter(pool_maxsize=concurrent, pool_block=True)
            self.mount('https://', a)
            self.mount('http://', a)

            # spoof user agent similar to what would be used when fetching files
            self.headers['User-Agent'] = 'Wget/1.20.3 (linux-gnu)'

        def send(self, req, **kwargs):
            # forcibly use the session timeout
            kwargs['timeout'] = self.timeout
            return super().send(req, **kwargs)


    class _UrlCheck(NetworkCheck):
        """Various URL related checks that require internet access."""

        feed_type = base.versioned_feed

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.checked = {}
            self.executor = concurrent.futures.ThreadPoolExecutor()
            self.reporter_lock = threading.Lock()
            self.timeout = self.options.timeout
            self.session = _Session(timeout=self.timeout)
            self.dead_result = None
            self.redirected_result = None

        def _http_check(self, url):
            """Check http:// and https:// URLs using requests."""
            result = None
            try:
                # suppress urllib3 SSL cert verification failure log messages
                with suppress_logging():
                    r = self.session.get(url)
                redirected_url = None
                for response in r.history:
                    if not response.is_permanent_redirect:
                        break
                    redirected_url = response.headers['location']
                if redirected_url:
                    result = partial(self.redirected_result, url, redirected_url)
            except requests.exceptions.SSLError as e:
                result = partial(SSLCertificateError, url, str(e))
            except requests.exceptions.RequestException as e:
                result = partial(self.dead_result, url, str(e))
            return result

        def _https_available_check(self, url):
            """Check https:// sites exist for http:// URLs."""
            result = None
            try:
                # suppress urllib3 SSL cert verification failure log messages
                with suppress_logging():
                    self.session.get(url)
                result = partial(HttpsUrlAvailable, f'http://{url[8:]}', url)
            except requests.exceptions.RequestException as e:
                pass
            return result

        def _ftp_check(self, url):
            """Check ftp:// URLs using urllib."""
            result = None
            try:
                response = urllib.request.urlopen(url, timeout=self.timeout)
            except urllib.error.URLError as e:
                result = partial(self.dead_result, url, str(e.reason))
            except socket.timeout as e:
                result = partial(self.dead_result, url, str(e))
            return result

        def _done(self, pkg, future):
            result = future.result()
            if result:
                self.options.reporter.report(result(pkg=pkg))

        def _get_urls(self, pkg):
            raise NotImplementedError

        def feed(self, pkg):
            http_urls, ftp_urls = partition(
                self._get_urls(pkg), predicate=lambda x: x.startswith('ftp://'))
            http_urls = tuple(http_urls)
            http_to_https_urls = (
                f'https://{url[7:]}' for url in http_urls if url.startswith('http://'))

            for urls, func in (
                    (http_urls, self._http_check),
                    (http_to_https_urls, self._https_available_check),
                    (ftp_urls, self._ftp_check),
                    ):
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

except ImportError:
    pass
