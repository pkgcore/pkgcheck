"""Various checks that require network support."""

import socket
import traceback
import urllib.request
from functools import partial

from lxml import etree
from pkgcore.fetch import fetchable

from .. import addons, results, sources
from . import NetworkCheck


class _UrlResult(results.VersionResult, results.Warning):
    """Generic result for a URL with some type of failed status."""

    def __init__(self, attr, url, message, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr
        self.url = url
        self.message = message

    @property
    def desc(self):
        if self.url in self.message:
            return f"{self.attr}: {self.message}"
        return f"{self.attr}: {self.message}: {self.url}"


class DeadUrl(_UrlResult):
    """Package with a dead URL of some type."""


class SSLCertificateError(_UrlResult):
    """Package with https:// HOMEPAGE with an invalid SSL cert."""

    @property
    def desc(self):
        if self.url in self.message:
            return f"{self.attr}: SSL cert error: {self.message}"
        return f"{self.attr}: SSL cert error: {self.message}: {self.url}"


class _UpdatedUrlResult(results.VersionResult, results.Warning):
    """Generic result for a URL that should be updated to an alternative."""

    message = None

    def __init__(self, attr, url, new_url, **kwargs):
        super().__init__(**kwargs)
        self.attr = attr
        self.url = url
        self.new_url = new_url

    @property
    def desc(self):
        msg = [self.attr]
        if self.message is not None:
            msg.append(self.message)
        msg.append(f"{self.url} -> {self.new_url}")
        return ": ".join(msg)


class RedirectedUrl(_UpdatedUrlResult):
    """Package with a URL that permanently redirects to a different site."""

    message = "permanently redirected"


class HttpsUrlAvailable(_UpdatedUrlResult):
    """URL uses http:// when https:// is available."""

    message = "HTTPS url available"


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
    """Generic URL verification check requiring network support."""

    _source = sources.LatestVersionRepoSource

    known_results = frozenset(
        [
            DeadUrl,
            RedirectedUrl,
            HttpsUrlAvailable,
            SSLCertificateError,
        ]
    )

    def _http_check(self, attr, url, *, pkg):
        """Verify http:// and https:// URLs."""
        result = None
        try:
            with self.session.get(url, allow_redirects=True, stream=True) as r:
                redirected_url = None
                for response in r.history:
                    if not response.is_permanent_redirect:
                        break
                    redirected_url = response.headers["location"]
                    hsts = "strict-transport-security" in response.headers

                if redirected_url:
                    if redirected_url.startswith("https://") and url.startswith("http://"):
                        result = HttpsUrlAvailable(attr, url, redirected_url, pkg=pkg)
                    elif redirected_url.startswith("http://") and hsts:
                        redirected_url = f"https://{redirected_url[7:]}"
                        result = RedirectedUrl(attr, url, redirected_url, pkg=pkg)
                    else:
                        result = RedirectedUrl(attr, url, redirected_url, pkg=pkg)
        except SSLError as e:
            result = SSLCertificateError(attr, url, str(e), pkg=pkg)
        except RequestError as e:
            result = DeadUrl(attr, url, str(e), pkg=pkg)
        return result

    def _https_available_check(self, attr, url, *, future, orig_url, pkg):
        """Check if https:// alternatives exist for http:// URLs."""
        result = None
        try:
            with self.session.get(url, allow_redirects=True, stream=True) as r:
                redirected_url = None
                for response in r.history:
                    if not response.is_permanent_redirect:
                        break
                    redirected_url = response.headers["location"]
                    hsts = "strict-transport-security" in response.headers

                # skip result if http:// URL check was redirected to https://
                if not isinstance(future.result(), HttpsUrlAvailable):
                    if redirected_url:
                        if redirected_url.startswith("https://"):
                            result = HttpsUrlAvailable(attr, orig_url, redirected_url, pkg=pkg)
                        elif redirected_url.startswith("http://") and hsts:
                            redirected_url = f"https://{redirected_url[7:]}"
                            result = HttpsUrlAvailable(attr, orig_url, redirected_url, pkg=pkg)
                    else:
                        result = HttpsUrlAvailable(attr, orig_url, url, pkg=pkg)
        except (RequestError, SSLError):
            pass
        return result

    def _ftp_check(self, attr, url, *, pkg):
        """Verify ftp:// URLs with urllib."""
        result = None
        try:
            urllib.request.urlopen(url, timeout=self.timeout)
        except urllib.error.URLError as e:
            result = DeadUrl(attr, url, str(e.reason), pkg=pkg)
        except socket.timeout as e:
            result = DeadUrl(attr, url, str(e), pkg=pkg)
        except UnicodeDecodeError:
            ...  # ignore ftp:// URLs that return binary data
        return result

    def task_done(self, pkg, attr, future):
        """Determine the result of a given URL verification task."""
        exc = future.exception()
        if exc is not None:
            # traceback can't be pickled so serialize it
            tb = traceback.format_exc()
            # return exceptions that occurred in threads
            self.results_q.put(tb)
            return

        result = future.result()
        if result is not None:
            if pkg is not None:
                # recreate result object with different pkg target and attr
                attrs = result._attrs.copy()
                attrs["attr"] = attr
                result = result._create(**attrs, pkg=pkg)
            self.results_q.put([result])

    def _get_urls(self, pkg):
        """Get URLs to verify for a given package."""
        raise NotImplementedError

    def _schedule_check(self, func, attr, url, executor, futures, **kwargs):
        """Schedule verification method to run in a separate thread against a given URL.

        Note that this tries to avoid hitting the network for the same URL
        twice using a mapping from requested URLs to future objects, adding
        result-checking callbacks to the futures of existing URLs.
        """
        future = futures.get(url)
        if future is None:
            future = executor.submit(func, attr, url, **kwargs)
            future.add_done_callback(partial(self.task_done, None, None))
            futures[url] = future
        else:
            future.add_done_callback(partial(self.task_done, kwargs["pkg"], attr))

    def schedule(self, pkg, executor, futures):
        """Schedule verification methods to run in separate threads for all flagged URLs."""
        http_urls = []
        for attr, url in self._get_urls(pkg):
            if url.startswith("ftp://"):
                self._schedule_check(self._ftp_check, attr, url, executor, futures, pkg=pkg)
            elif url.startswith(("https://", "http://")):
                self._schedule_check(self._http_check, attr, url, executor, futures, pkg=pkg)
                http_urls.append((attr, url))

        http_urls = tuple(http_urls)
        http_to_https_urls = (
            (attr, url, f"https://{url[7:]}")
            for (attr, url) in http_urls
            if url.startswith("http://")
        )
        for attr, orig_url, url in http_to_https_urls:
            future = futures[orig_url]
            self._schedule_check(
                self._https_available_check,
                attr,
                url,
                executor,
                futures,
                future=future,
                orig_url=orig_url,
                pkg=pkg,
            )


class HomepageUrlCheck(_UrlCheck):
    """Verify HOMEPAGE URLs."""

    def _get_urls(self, pkg):
        for url in pkg.homepage:
            yield "HOMEPAGE", url


class FetchablesUrlCheck(_UrlCheck):
    """Verify SRC_URI URLs."""

    required_addons = (addons.UseAddon,)

    def __init__(self, *args, use_addon, **kwargs):
        super().__init__(*args, **kwargs)
        self.fetch_filter = use_addon.get_filter("fetchables")

    def _get_urls(self, pkg):
        # ignore conditionals
        fetchables, _ = self.fetch_filter(
            (fetchable,),
            pkg,
            pkg.generate_fetchables(
                allow_missing_checksums=True, ignore_unknown_mirrors=True, skip_default_mirrors=True
            ),
        )
        for f in fetchables.keys():
            for url in f.uri:
                yield "SRC_URI", url


class MetadataUrlCheck(_UrlCheck):
    """Verify metadata.xml URLs."""

    _source = sources.PackageRepoSource

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.protocols = ("http://", "https://", "ftp://")
        self.remote_map = {
            "bitbucket": "https://bitbucket.org/{project}",
            "codeberg": "https://codeberg.org/{project}",
            "cpan": "https://metacpan.org/dist/{project}",
            # some packages include a lot of modules, and scanning them
            # DoS-es metacpan
            # 'cpan-module': 'https://metacpan.org/pod/{project}',
            "cran": "https://cran.r-project.org/web/packages/{project}/",
            "ctan": "https://ctan.org/pkg/{project}",
            "freedesktop-gitlab": "https://gitlab.freedesktop.org/{project}.git/",
            "gentoo": "https://gitweb.gentoo.org/{project}.git/",
            "github": "https://github.com/{project}",
            "gitlab": "https://gitlab.com/{project}",
            "gnome-gitlab": "https://gitlab.gnome.org/{project}.git/",
            "hackage": "https://hackage.haskell.org/package/{project}",
            "kde-invent": "https://invent.kde.org/{project}",
            "launchpad": "https://launchpad.net/{project}",
            "osdn": "https://osdn.net/projects/{project}/",
            "pecl": "https://pecl.php.net/package/{project}",
            "pypi": "https://pypi.org/project/{project}/",
            "rubygems": "https://rubygems.org/gems/{project}",
            "savannah": "https://savannah.gnu.org/projects/{project}",
            "savannah-nongnu": "https://savannah.nongnu.org/projects/{project}",
            "sourceforge": "https://sourceforge.net/projects/{project}/",
            "sourcehut": "https://sr.ht/{project}/",
            "vim": "https://vim.org/scripts/script.php?script_id={project}",
            # these platforms return 200 for errors, so no point in trying
            # 'google-code': 'https://code.google.com/archive/p/{project}/',
            # 'heptapod': 'https://foss.heptapod.net/{project}',
            # 'pear': 'https://pear.php.net/package/{project}',
        }

    def _get_urls(self, pkg):
        try:
            tree = etree.parse(pkg._shared_pkg_data.metadata_xml._source)
        except (OSError, etree.XMLSyntaxError):
            return

        # TODO: move upstream parsing to a pkgcore attribute?
        for element in ("changelog", "doc", "bugs-to", "remote-id"):
            for x in tree.xpath(f"//upstream/{element}"):
                if x.text:
                    url = x.text
                    if element == "remote-id":
                        # Use remote-id -> URL map to determine actual URL,
                        # skipping verification for unmapped remote-ids.
                        try:
                            url = self.remote_map[x.attrib["type"]].format(project=url)
                        except KeyError:
                            continue
                    # skip unsupported protocols, e.g. mailto URLs from bugs-to
                    if url.startswith(self.protocols):
                        yield f"metadata.xml: {element}", url

    def schedule(self, pkgs, *args, **kwargs):
        super().schedule(pkgs[-1], *args, **kwargs)
