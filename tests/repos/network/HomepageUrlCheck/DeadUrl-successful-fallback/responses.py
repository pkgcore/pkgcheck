from requests.models import Response

r1 = Response()
r1.status_code = 405
r1.reason = 'Method Not Allowed'
r1.url = 'https://github.com/pkgcore/pkgcheck'
r2 = Response()
r2.status_code = 200
r2.reason = 'OK'
r2.url = 'https://github.com/pkgcore/pkgcheck'
responses = [r1, r2]
