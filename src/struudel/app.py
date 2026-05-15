from datetime import timedelta

from flask import Flask
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix

from struudel.blueprints import register_blueprints
from struudel.cli import superuser_cli
from struudel.config import settings
from struudel.csrf import init_csrf
from struudel.extensions import oauth, session_redis_client
from struudel.request_hooks import init_request_hooks
from struudel.template_filters import init_template_filters
from struudel.template_globals import init_template_globals


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.secret_key
    app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

    app.config["SESSION_TYPE"] = "redis"
    app.config["SESSION_REDIS"] = session_redis_client
    app.config["SESSION_KEY_PREFIX"] = "struudel:session:"
    app.config["SESSION_PERMANENT"] = True
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=settings.session_lifetime_hours)
    app.config["SESSION_COOKIE_NAME"] = settings.session_cookie_name
    app.config["SESSION_COOKIE_SECURE"] = settings.session_cookie_secure
    app.config["SESSION_COOKIE_HTTPONLY"] = settings.session_cookie_httponly
    app.config["SESSION_COOKIE_SAMESITE"] = settings.session_cookie_samesite
    Session(app)

    app.config["WTF_CSRF_TIME_LIMIT"] = None
    init_csrf(app)

    oauth.init_app(app)
    oauth.register(
        name="oidc",
        server_metadata_url=settings.oidc_discovery_url,
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        client_kwargs={"scope": settings.oidc_scopes},
    )

    register_blueprints(app)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)  # ty: ignore[invalid-assignment]

    init_template_filters(app)
    init_template_globals(app)
    init_request_hooks(app)

    app.cli.add_command(superuser_cli)

    return app
