from contextlib import contextmanager

from requests.models import Response


@contextmanager
def responses(req, **kwargs):
    possible_responses = {
        # success
        "minisig": {
            "status_code": 200,
            "reason": "OK",
            "headers": {"Content-Type": "application/pgp-signature"},
        },
        # false success (like 404 behind authentication redirect)
        "sign": {
            "status_code": 200,
            "reason": "OK",
            "headers": {"Content-Type": "text/html"},
        },
    }

    r = Response()
    r.status_code = 404
    r.reason = "Not Found"

    possible_response = possible_responses.get(req.url.split(".")[-1])
    if possible_response is not None:
        for key, value in possible_response.items():
            setattr(r, key, value)
    yield r
