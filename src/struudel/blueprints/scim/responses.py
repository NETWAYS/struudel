from typing import Any

from flask import jsonify
from werkzeug.wrappers import Response

from struudel.services.scim import SCIM_CONTENT_TYPE, error_response


def scim_response(body: Any, status: int = 200) -> Response:
    response = jsonify(body)
    response.status_code = status
    response.mimetype = SCIM_CONTENT_TYPE
    return response


def scim_error(status: int, detail: str, scim_type: str | None = None) -> Response:
    return scim_response(error_response(status, detail, scim_type), status)
