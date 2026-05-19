#!/bin/sh
set -eu

role="${1:-app}"
shift || true

case "$role" in
  app)
    alembic upgrade head
    if [ "${APP_ENV:-prod}" = "dev" ]; then
      exec flask --app struudel.app run --host=0.0.0.0 --port=5009 --debug
    else
      exec gunicorn \
        --workers "${GUNICORN_WORKERS:-4}" \
        --bind 0.0.0.0:5009 \
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
