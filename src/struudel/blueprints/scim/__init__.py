from flask import Blueprint, request

from struudel.config import settings

bp = Blueprint("scim", __name__, url_prefix="/scim/v2")


# SCIM provisioning of large groups (PATCH with thousands of member ops, or
# PUT of a fully-replaced member list) can exceed the global 1 MiB body
# limit. Raise it for SCIM requests only by overriding the per-request
# attribute that Werkzeug consults before parsing the body.
@bp.before_request
def _lift_max_content_length() -> None:
    request.max_content_length = settings.scim_max_content_length


from struudel.blueprints.scim import routes  # noqa: E402, F401
