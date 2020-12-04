from requests.models import Response

r = Response()
r.status_code = 404
r.reason = 'Not Found'
r.url = 'https://github.com/pkgcore/pkgcheck'
responses = [r]
