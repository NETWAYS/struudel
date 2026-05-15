from flask import Blueprint

bp = Blueprint("scim", __name__, url_prefix="/scim/v2")

from struudel.blueprints.scim import routes  # noqa: E402, F401
