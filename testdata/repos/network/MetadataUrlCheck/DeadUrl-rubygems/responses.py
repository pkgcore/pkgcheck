import io

from requests.models import Response

r = Response()
r.status_code = 404
r.reason = 'Not Found'
r.url = 'https://rubygems.org/gems/pkgcheck'
r.raw = io.StringIO()
responses = [r]
