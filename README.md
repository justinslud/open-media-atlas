# Open Media Atlas

Open Media Atlas (OMA) is a compact, cross-media reference catalog for discovering works and following adaptations and other creative relationships. Public browsing needs no account; visitors may also create an unprivileged account with a public username and private, verified email address.

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

### Account email configuration

Local development uses Django's console email backend by default, so verification
and reset links appear in the developer terminal. Automated tests explicitly use
the in-memory test backend. Production uses SMTP and defaults to `localhost` when
an SMTP host has not been configured. This keeps build and administrative commands
usable before optional mail credentials are supplied; delivery attempts fail
honestly in the account UI until a reachable SMTP provider is configured.

Configure an SMTP provider with credentials obtained from that provider (OMA does
not provision or require a paid service):

| Variable | Required production value |
| --- | --- |
| `EMAIL_HOST` | SMTP hostname; defaults to `localhost` |
| `EMAIL_PORT` | SMTP port; defaults to `587` |
| `EMAIL_HOST_USER` | SMTP username, if the provider requires one |
| `EMAIL_HOST_PASSWORD` | SMTP password or API credential, stored as a secret |
| `EMAIL_USE_TLS` | `true` for STARTTLS (default) |
| `EMAIL_USE_SSL` | `true` only for implicit TLS; do not enable with STARTTLS |
| `DEFAULT_FROM_EMAIL` | Verified sender, for example `Open Media Atlas <accounts@example.org>` |
| `EMAIL_VERIFICATION_TIMEOUT_HOURS` | Verification-link lifetime; defaults to `24` |
| `EMAIL_BACKEND` | Optional backend override; leave SMTP in production |

After deployment, create a normal test account, confirm receipt and sender
authentication, verify it, request a password reset, confirm the old links cannot
be reused, and check that an ordinary account has neither staff status nor access
to `/admin/`. Also confirm `/`, `/discover/`, and public work pages remain usable
while logged out. Delivery failures are reported honestly in the UI and can be
retried; links are never rendered into public pages or production logs.

## Milestone scope

- Title search and media-type filtering, including HTMX partial result updates.
- Public-only work pages with compact facts, creators, fictional source references, inverse-aware relationship labels, and inline versions/releases.
- Idempotent fictional fixtures: one novel, two independent film adaptations, and an embedded translation with two editions.
- Admin CRUD for every milestone entity.
- Signup, login/logout, email verification, password reset, and a compact account page, with database-backed abuse limits that work across web workers.

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

### Load the real starter catalog

Imports are deliberately **not** part of `build.sh`: a deploy never makes
third-party requests or changes catalog content unexpectedly. After the new
migration has deployed, open the web service's **Shell** tab and run:

```bash
python manage.py import_openlibrary --file data/openlibrary-curated.txt --limit 24 --dry-run
python manage.py import_openlibrary --file data/openlibrary-curated.txt --limit 24
python manage.py load_curated_relationships
```

The first command validates the bounded selection without writing. The second
imports 24 selected Open Library works and records an inspectable import run;
the third adds three reviewed film relationships and the initial editable
homepage selection. Both writing commands are safe to repeat. Once any real
public record exists, demonstration records remain in admin but are omitted
from public pages.

For an ad hoc bounded import, pass explicit IDs instead:

```bash
python manage.py import_openlibrary OL872932W OL39745868W --limit 2
```

Inspect runs and per-item created/updated/skipped/failed results under **Import
runs** in Django admin. Imported source snapshots remain distinct from accepted
catalog fields; reimports update an unchanged imported value but preserve a
manual editorial override. No rights status or generated description is added.
To retry only failures from a run, use
`python manage.py import_openlibrary --retry-run RUN_ID --limit 24`.

To avoid charges, do not apply the Blueprint. If staging is no longer needed,
delete both the web service and database in Render; suspending only the web
service does not necessarily stop database billing. Render displays the exact
prorated charges before creation and in the Billing page.
