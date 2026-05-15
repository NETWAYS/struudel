from datetime import UTC, datetime

from flask import g, render_template

from struudel.auth import require_auth
from struudel.blueprints.dashboard import bp
from struudel.database import SessionLocal
from struudel.services import poll as poll_service


@bp.route("/")
@require_auth
def index() -> str:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        data = poll_service.get_dashboard_data(db, user_id=g.user["id"], now=now)
    return render_template("dashboard/index.html", data=data, now=now)
