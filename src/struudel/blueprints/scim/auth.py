import hmac
from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import request

from struudel.blueprints.scim.responses import scim_error
from struudel.config import settings


def require_scim_token(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        configured = settings.scim_token
        if not configured:
            return scim_error(503, "SCIM endpoint is not configured")

        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        # hmac.compare_digest is constant-time only between equal-length
        # inputs; check length first so the equal-length comparison is the
        # only thing that ever runs against the real secret.
        if (
            scheme.lower() != "bearer"
            or len(token) != len(configured)
            or not hmac.compare_digest(token, configured)
        ):
            response = scim_error(401, "Missing or invalid bearer token")
            response.headers["WWW-Authenticate"] = 'Bearer realm="scim"'
            return response

        return view(*args, **kwargs)

    return wrapper
