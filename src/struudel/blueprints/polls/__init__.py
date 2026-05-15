from flask import Blueprint

bp = Blueprint("polls", __name__, url_prefix="/polls", template_folder="templates")

from struudel.blueprints.polls import routes  # noqa: E402, F401
