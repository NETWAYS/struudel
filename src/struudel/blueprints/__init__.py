from flask import Flask

from struudel.blueprints.admin import bp as admin_bp
from struudel.blueprints.auth import bp as auth_bp
from struudel.blueprints.dashboard import bp as dashboard_bp
from struudel.blueprints.health import bp as health_bp
from struudel.blueprints.polls import bp as polls_bp
from struudel.blueprints.scim import bp as scim_bp
from struudel.blueprints.user import bp as user_bp
from struudel.csrf import csrf


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(polls_bp)
    app.register_blueprint(scim_bp)
    app.register_blueprint(user_bp)

    csrf.exempt(scim_bp)
