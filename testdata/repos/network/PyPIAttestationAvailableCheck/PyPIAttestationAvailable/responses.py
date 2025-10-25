import io

from requests.models import Response

r = Response()
r.status_code = 200
r.reason = "OK"
r.url = "https://pypi.org/integrity/PyPIAttestationAvailable/v0/pypiattestationavailable-0.tar.gz/provenance"
r.raw = io.StringIO()

responses = [r]
