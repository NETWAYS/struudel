from flask import Flask, g, session
from werkzeug.wrappers import Response

from struudel.database import SessionLocal
from struudel.services.user import get_user_auth_status

# Alpine.js evaluates `x-data` / `@click` / `x-show` etc. via `new Function()` at
# runtime, which requires `script-src 'unsafe-eval'`. All other JS lives in static
# files under /static/js/ and is loaded as `<script src="...">`, so we don't need
# `'unsafe-inline'` for scripts. `style-src 'unsafe-inline'` stays — Alpine and
# inline `<style>` rules in third-party CSS rely on it.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def init_request_hooks(app: Flask) -> None:
    @app.before_request
    def load_current_user() -> None:
        session_user = session.get("user")
        if session_user is None:
            g.user = None
            return

        with SessionLocal() as db:
            status = get_user_auth_status(db, user_id=session_user["id"])

        if status is None or not status.is_active:
            session.clear()
            g.user = None
            return

        g.user = {**session_user, "is_superuser": status.is_superuser}

    @app.after_request
    def set_security_headers(response: Response) -> Response:
        response.headers.setdefault("Content-Security-Policy", _CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response
