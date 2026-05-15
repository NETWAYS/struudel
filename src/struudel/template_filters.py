from datetime import datetime

from flask import Flask, url_for

from struudel.timezones import to_local
from struudel.version import COMMIT


def localtime(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if value is None:
        return ""
    return to_local(value).strftime(fmt)


def static_url(filename: str) -> str:
    """Build a static URL with a cache-busting `v=<commit>` query parameter.

    Uses the git commit so URLs change on every deploy and browsers re-fetch
    rebuilt assets, while staying stable within a single deploy.
    """
    return f"{url_for('static', filename=filename)}?v={COMMIT}"


def init_template_filters(app: Flask) -> None:
    app.jinja_env.filters["localtime"] = localtime
    app.add_template_global(static_url, name="static_url")
