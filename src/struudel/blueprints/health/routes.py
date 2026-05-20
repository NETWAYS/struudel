import sqlalchemy as sa
from flask import current_app, jsonify
from redis.exceptions import RedisError
from werkzeug.wrappers import Response

from struudel.blueprints.health import bp
from struudel.database import SessionLocal
from struudel.extensions import app_state_redis_client, session_redis_client


@bp.route("/live")
def live() -> Response:
    return jsonify(status="ok")


@bp.route("/ready")
def ready() -> Response | tuple[Response, int]:
    for name, client in (
        ("session", session_redis_client),
        ("app_state", app_state_redis_client),
    ):
        try:
            client.ping()
        except RedisError as e:
            current_app.logger.warning("Readiness check failed (%s redis): %s", name, e)
            return jsonify(status="unavailable", detail=f"{name} redis unreachable"), 503

    try:
        with SessionLocal() as db:
            db.execute(sa.text("SELECT 1"))
    except Exception as e:
        current_app.logger.warning("Readiness check failed (database): %s", e)
        return jsonify(status="unavailable", detail="database unreachable"), 503

    return jsonify(status="ok")
