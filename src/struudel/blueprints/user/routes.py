from flask import g
from werkzeug.wrappers import Response

from struudel.auth import require_auth
from struudel.blueprints.user import bp
from struudel.database import SessionLocal
from struudel.services.user import get_cached_avatar


@bp.route("/avatar")
@require_auth
def avatar() -> Response:
    with SessionLocal() as db:
        cached = get_cached_avatar(db, user_id=g.user["id"])

    if cached is None:
        return Response(status=404)
    return Response(cached, content_type="image/png")
