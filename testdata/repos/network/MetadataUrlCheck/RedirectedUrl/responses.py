import io

from requests.models import Response

r_hist = Response()
r_hist.status_code = 301
r_hist.reason = 'Moved Permanently'
r_hist.url = 'https://github.com/pkgcore/pkgcheck/changelog'
r_hist.headers = {'location': 'https://github.com/pkgcore/pkgcheck/news'}
r_hist.raw = io.StringIO()

r1 = Response()
r1.status_code = 200
r1.reason = 'OK'
r1.url = 'https://github.com/pkgcore/pkgcheck/changelog'
r1.raw = io.StringIO()
r1.history = [r_hist]

r_hist = Response()
r_hist.status_code = 301
r_hist.reason = 'Moved Permanently'
r_hist.url = 'https://github.com/pkgcore/pkgcheck'
r_hist.headers = {'location': 'https://github.com/pkgcore/pkgcheck/'}
r_hist.raw = io.StringIO()

r2 = Response()
r2.status_code = 301
r2.reason = 'OK'
r2.url = 'https://github.com/pkgcore/pkgcheck'
r2.raw = io.StringIO()
r2.history = [r_hist]

responses = [r1, r2]
