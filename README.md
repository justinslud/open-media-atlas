# Open Media Atlas

Open Media Atlas (OMA) is a compact, cross-media reference catalog for discovering works and following adaptations and other creative relationships. This milestone implements public home, discovery, and work-detail pages plus Django administration using deliberately fictional demonstration data.

## Setup and preview

Requires Python 3.12+ and PostgreSQL 16+ for a production-like environment. SQLite is the zero-configuration local development fallback.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # export values manually or with: set -a; . ./.env; set +a
export DJANGO_DEBUG=true
python manage.py migrate
python manage.py load_demo_catalog
python manage.py runserver 0.0.0.0:8000
```

After setup, the single startup command is `DJANGO_DEBUG=true python manage.py runserver 0.0.0.0:8000`. Preview at <http://127.0.0.1:8000/>. Create an admin login with `python manage.py createsuperuser`, then use <http://127.0.0.1:8000/admin/>.

For PostgreSQL, set `DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME`. In production, set a strong `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, and HTTPS origins in `DJANGO_CSRF_TRUSTED_ORIGINS`; leave `DJANGO_DEBUG` false.

## Milestone scope

- Title search and media-type filtering, including HTMX partial result updates.
- Public-only work pages with compact facts, creators, fictional source references, inverse-aware relationship labels, and inline versions/releases.
- Idempotent fictional fixtures: one novel, two independent film adaptations, and an embedded translation with two editions.
- Admin CRUD for every milestone entity.

Bulk ingestion, community editing, terms workflows, claims, rights conclusions, comments, recommendations, and licensing are deliberately deferred. The next recommended milestone is a sourced proposal/review flow with revision history, followed by controlled vocabulary suggestions.

