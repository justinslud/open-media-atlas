#!/usr/bin/env bash
set -o errexit
set -o pipefail
set -o nounset

python -m pip install --disable-pip-version-check -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py load_demo_catalog

