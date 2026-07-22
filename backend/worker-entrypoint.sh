#!/bin/sh
set -eu

concurrency="${CELERY_WORKER_CONCURRENCY:-1}"
case "$concurrency" in
  1|2) ;;
  *)
    echo "CELERY_WORKER_CONCURRENCY 必须是 1 或 2，当前值为: $concurrency" >&2
    exit 64
    ;;
esac

exec celery -A app.workers.celery_app:celery_app worker \
  --loglevel=INFO \
  --concurrency="$concurrency"
