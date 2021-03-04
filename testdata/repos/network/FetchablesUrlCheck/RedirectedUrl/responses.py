import io

from requests.models import Response

r_hist = Response()
r_hist.status_code = 301
r_hist.reason = 'Moved Permanently'
r_hist.url = 'https://github.com/pkgcore/pkgcheck/foo.tar.gz'
r_hist.headers = {'location': 'https://github.com/pkgcore/pkgcheck/foo-moved.tar.gz'}
r_hist.raw = io.StringIO()

r = Response()
r.status_code = 200
r.reason = 'OK'
r.url = 'https://github.com/pkgcore/pkgcheck/foo.tar.gz'
r.history = [r_hist]
r.raw = io.StringIO()

responses = [r]
