from flask import Blueprint

bp = Blueprint("dashboard", __name__, template_folder="templates")

from struudel.blueprints.dashboard import routes  # noqa: E402, F401
