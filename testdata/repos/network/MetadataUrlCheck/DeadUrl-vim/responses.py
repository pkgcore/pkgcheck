import io

from requests.models import Response

r = Response()
r.status_code = 404
r.reason = 'Not Found'
r.url = 'https://vim.org/scripts/script.php?script_id=12345'
r.raw = io.StringIO()
responses = [r]
