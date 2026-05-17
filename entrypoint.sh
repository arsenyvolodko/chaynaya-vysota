#!/bin/sh

if [ -n "$SQL_HOST" ] && [ -n "$SQL_PORT" ]; then
    echo "Waiting for postgres at $SQL_HOST:$SQL_PORT..."
    while ! nc -z "$SQL_HOST" "$SQL_PORT"; do
      sleep 0.1
    done
    echo "PostgreSQL started"
fi

set -e

python3 manage.py migrate
python3 manage.py collectstatic --noinput

gunicorn chaynaya_vysota.asgi:application \
  -k uvicorn.workers.UvicornWorker \
  -w 1 \
  -b 0.0.0.0:8000 \
  --timeout 120 \
  --graceful-timeout 30 \
  --access-logfile -