"""Core check classes."""

from multiprocessing import cpu_count

from .. import base, sources
from ..log import logger


class GentooRepoCheck(base.Check):
    """Check that is only valid when run against the gentoo repo."""

    @classmethod
    def skip(cls, namespace):
        skip = not namespace.gentoo_repo
        if skip:
            logger.info(f'skipping {cls.__name__}, not running against gentoo repo')
        return skip or super().skip(namespace)


class OverlayRepoCheck(base.Check):
    """Check that is only valid when run against an overlay repo."""

    @classmethod
    def skip(cls, namespace):
        skip = not namespace.target_repo.masters
        if skip:
            logger.info(f'skipping {cls.__name__}, not running against overlay repo')
        return skip or super().skip(namespace)


class ExplicitlyEnabledCheck(base.Check):
    """Check that is only valid when explicitly enabled."""

    @classmethod
    def skip(cls, namespace):
        if namespace.selected_checks is not None:
            disabled, enabled = namespace.selected_checks
        else:
            disabled, enabled = [], []

        # enable checks for selected keywords
        keywords = namespace.filtered_keywords
        if keywords is not None:
            keywords = keywords.intersection(cls.known_results)

        enabled += namespace.forced_checks
        skip = cls.__name__ not in enabled and not keywords
        if skip:
            logger.info(f'skipping {cls.__name__}, not explicitly enabled')
        return skip or super().skip(namespace)


class NetworkCheck(base.Check):
    """Check requiring internet access."""

    @classmethod
    def skip(cls, namespace):
        skip = not namespace.net
        if skip:
            logger.info(f'skipping {cls.__name__}, network checks not enabled')
        elif 'requests_session' not in namespace:
            import requests
            from .network import RequestError, SSLError

            class Session(requests.Session):
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
                    try:
                        return super().send(req, **kwargs)
                    except requests.exceptions.SSLError as e:
                        raise SSLError(e)
                    except requests.exceptions.RequestException as e:
                        raise RequestError(e)

            # inject requests session into namespace for multiple network checks to use
            namespace.requests_session = Session(timeout=namespace.timeout)
        return skip or super().skip(namespace)
