from flask import Flask, render_template
from flask_wtf.csrf import CSRFError, CSRFProtect

csrf = CSRFProtect()


def init_csrf(app: Flask) -> None:
    csrf.init_app(app)

    @app.errorhandler(CSRFError)
    def _handle_csrf_error(e: CSRFError) -> tuple[str, int]:
        return render_template("errors/csrf.html", reason=e.description), 400
