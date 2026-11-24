#!/bin/sh
# Run migrations only when the platform asks for it (Render sets
# RUN_MIGRATIONS=true). Docker Compose keeps managing migrations in its own
# command, so local and self-hosted starts are unchanged.
set -eu

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    python manage.py migrate --noinput
fi

exec "$@"
