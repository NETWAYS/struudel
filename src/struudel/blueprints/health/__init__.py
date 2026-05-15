from flask import Blueprint

bp = Blueprint("health", __name__, url_prefix="/_health")

from struudel.blueprints.health import routes  # noqa: E402, F401
