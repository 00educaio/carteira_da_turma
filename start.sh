#!/usr/bin/env bash
set -o errexit
python manage.py migrate --noinput
exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 120
