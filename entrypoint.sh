#!/bin/sh
set -e
case "$1" in
  celery)
    # The web service owns schema and static initialization. Starting these
    # in every worker/beat container creates concurrent migration races.
    ;;
  *)
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
    ;;
esac
exec "$@"
