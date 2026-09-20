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

## Hosted staging on Render

This repository includes a Render Blueprint for one Django web service and one
PostgreSQL database. It uses paid staging-sized plans deliberately: Render's
free PostgreSQL databases expire, making them unsuitable for a stable review
URL. Applying the Blueprint provisions paid resources, so stop before the final
confirmation unless the listed charges are approved.

1. Push this branch to a GitHub repository you control.
2. Create or sign in to a Render account at <https://dashboard.render.com/> and
   connect GitHub when prompted. Grant access only to the OMA repository.
3. Choose **New → Blueprint**, select the repository and branch, and confirm
   that Render detects `render.yaml`.
4. Review the two resources and their displayed monthly prices. The committed
   configuration requests a Starter web service and Basic-256mb PostgreSQL.
   Their currently expected base prices are **US$7/month + US$6/month =
   US$13/month**, before applicable tax and any usage overages. Pricing could
   change, so treat the exact total shown by Render before creation as
   authoritative. Add a payment method only after approving that total, then
   apply.
5. When the deployment is healthy, open the generated
   `https://open-media-atlas-….onrender.com/` URL. Render injects the database
   URL and a generated secret; debug mode remains off.

Each deploy runs `build.sh`, which installs pinned packages, collects compressed
static files, applies migrations, and idempotently refreshes demonstration data.
WhiteNoise serves versioned static assets from the Django service. The service
health check is `/health/`.

No default administrator is created. To add one later, use the Render service's
Shell tab and run `python manage.py createsuperuser`; enter a unique password in
that private prompt. Never place admin credentials in Blueprint variables.

To avoid charges, do not apply the Blueprint. If staging is no longer needed,
delete both the web service and database in Render; suspending only the web
service does not necessarily stop database billing. Render displays the exact
prorated charges before creation and in the Billing page.
