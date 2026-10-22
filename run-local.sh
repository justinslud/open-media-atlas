#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
# Always use the local SQLite demo, even if the shell has a hosted DATABASE_URL.
export DATABASE_URL=
export DJANGO_DEBUG=true
exec .venv/bin/python manage.py runserver 127.0.0.1:8000
