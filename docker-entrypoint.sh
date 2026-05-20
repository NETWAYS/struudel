#!/bin/sh
set -eu

role="${1:-app}"
shift || true

case "$role" in
  app)
    # Retry alembic in case Postgres is briefly unavailable on startup
    # (compose `depends_on: service_healthy` covers cold-start but not
    # mid-life restarts). Max ~60s — fails fast for genuine migration
    # errors because alembic itself returns immediately then.
    i=0
    until alembic upgrade head; do
      i=$((i + 1))
      if [ "$i" -ge 30 ]; then
        echo "alembic upgrade head failed after 30 attempts" >&2
        exit 1
      fi
      echo "alembic upgrade head failed (attempt $i), retrying in 2s..." >&2
      sleep 2
    done
    if [ "${APP_ENV:-prod}" = "dev" ]; then
      exec flask --app struudel.app run --host=0.0.0.0 --port=5009 --debug
    else
      # --forwarded-allow-ips '*' so gunicorn honours X-Forwarded-* from
      #   any reverse proxy (operator can tighten this via env if needed).
      # --worker-tmp-dir /dev/shm avoids disk I/O for gunicorn worker
      #   heartbeat files.
      # --timeout / --graceful-timeout: long-running SCIM bulk and
      #   long-polling endpoints need more than gunicorn's 30s default;
      #   graceful shutdown gets 30s to drain in-flight requests.
      exec gunicorn \
        --workers "${GUNICORN_WORKERS:-4}" \
        --bind 0.0.0.0:5009 \
        --timeout "${GUNICORN_TIMEOUT:-60}" \
        --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
        --worker-tmp-dir /dev/shm \
        --forwarded-allow-ips "${GUNICORN_FORWARDED_ALLOW_IPS:-*}" \
        --access-logfile - \
        --error-logfile - \
        "struudel.app:create_app()"
    fi
    ;;
  worker)
    exec huey_consumer \
      -k thread \
      -w "${HUEY_WORKERS:-4}" \
      struudel.tasks.huey
    ;;
  *)
    exec "$role" "$@"
    ;;
esac
