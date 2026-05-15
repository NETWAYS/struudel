from flask import Blueprint

bp = Blueprint("user", __name__, url_prefix="/user")

from struudel.blueprints.user import routes  # noqa: E402, F401
