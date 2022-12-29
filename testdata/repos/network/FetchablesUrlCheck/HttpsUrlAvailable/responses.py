import io

from requests.models import Response

# initial URL check
r = Response()
r.status_code = 200
r.reason = "OK"
r.url = "http://github.com/pkgcore/pkgcheck/foo.tar.gz"
r.raw = io.StringIO()
# now checking if https:// exists
https_r = Response()
https_r.status_code = 200
https_r.reason = "OK"
https_r.url = "https://github.com/pkgcore/pkgcheck/foo.tar.gz"
https_r.raw = io.StringIO()

responses = [r, https_r]
