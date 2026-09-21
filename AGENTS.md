# Open Media Atlas contributor guide

## Stack and layout

- Django monolith, server-rendered templates, HTMX for targeted updates, PostgreSQL in deployed environments (SQLite is the local/test fallback).
- Project configuration: `oma/`; catalog domain, views, admin, fixtures, and tests: `catalog/`; templates: `templates/`; design tokens/styles: `static/css/oma.css`.

## Commands

- Setup: `python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`
- Migrate: `python manage.py migrate`
- Load/update demo fixtures: `python manage.py load_demo_catalog`
- Dry-run curated import: `python manage.py import_openlibrary --file data/openlibrary-curated.txt --limit 24 --dry-run`
- Import curated records: `python manage.py import_openlibrary --file data/openlibrary-curated.txt --limit 24`
- Seed reviewed relationships: `python manage.py load_curated_relationships`
- Run after setup: `DJANGO_DEBUG=true python manage.py runserver 0.0.0.0:8000`
- Test: `DJANGO_DEBUG=true python manage.py test`
- Migration check: `DJANGO_DEBUG=true python manage.py makemigrations --check --dry-run`

## Planning references

- Use the page/action map for journeys and page behavior; permissions matrix for publication and authority boundaries.
- Use `schema.dbml` for domain direction and constraints, but implement only milestone entities.
- Use the example catalog for synthetic fixtures, the data-source map for provenance/import decisions, and the visual design language for UI work.

## Conventions and deferred scope

- Keep stable database IDs canonical, external identifiers separate, relationships record-to-record, and fixtures idempotent. Public queries must explicitly filter visibility and relationship review status.
- Versions stay embedded by default; standalone presentation never changes version identity. Never infer rights ownership from credits or representation claims.
- Do not add bulk ingestion, AI enrichment, transactions/licensing, comments, recommendations, public editing, or new infrastructure without a scoped milestone.
- Never commit secrets or portray fictional fixture facts as real.
- Never run network imports during a web request, build, migration, or startup. Always use explicit IDs and a bounded `--limit`.

