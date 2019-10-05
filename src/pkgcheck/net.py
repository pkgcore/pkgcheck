"""Various support for network checks."""

import os
import logging

import requests
# suppress all urllib3 log messages
logging.getLogger('urllib3').propagate = False

from .checks.network import RequestError, SSLError


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
        concurrent = concurrent if concurrent is not None else os.cpu_count() * 5
        a = requests.adapters.HTTPAdapter(pool_maxsize=concurrent, pool_block=True)
        self.mount('https://', a)
        self.mount('http://', a)

        # spoof user agent similar to what would be used when fetching files
        self.headers['User-Agent'] = 'Wget/1.20.3 (linux-gnu)'

    def send(self, req, **kwargs):
        # forcibly use the session timeout
        kwargs['timeout'] = self.timeout
        try:
            r = super().send(req, **kwargs)
            r.raise_for_status()
            return r
        except requests.exceptions.SSLError as e:
            raise SSLError(e)
        except requests.exceptions.ConnectionError as e:
            raise RequestError(e, 'connection failed')
        except requests.exceptions.RequestException as e:
            raise RequestError(e)
