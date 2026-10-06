# Useful, annotated collections

Chunk 3 extends `MediaList` and `MediaListEntry`. Start at **Public collections**
(`/lists/`), a collection detail page, or **Add to collection** on any public work.
Owner editing lives at the existing `/me/lists/<id>/edit/` route.

## Behavior

- Collection pages show introductions, public username attribution, visibility,
  available-work counts, ordered entries, public type/date display helpers, and
  optional **Why this belongs here** annotations. The existing type-mark fallback
  is retained: the current catalog has no stored cover/thumbnail field.
- Public discovery has title/introduction/curator search, up to three ordered
  available-work previews per collection, and pagination that retains the query.
  Private collections and unpublished work details are excluded.
- A collection with no available works explains that it is still being assembled.
  Owners get an add-first-work link; owners also retain unavailable-entry warnings.
  Database/server failures remain errors, rather than being rendered as empty data.
- The work-page chooser searches only the member's own collections, shows current
  membership and visibility, and allows creating and adding in one step. Existing
  account login/signup links preserve the intended work. Creation defaults private;
  publishing still requires verified email. Adding redirects to the collection
  with a confirmation, including clean handling of an already-included work.
- Owners can edit title/introduction/visibility, search existing catalog works,
  annotate, remove membership, and reorder with keyboard-accessible move buttons.
  Boundary move buttons are disabled. Search uses existing catalog matching and
  does not change curated order. Membership/annotation/order changes update the
  collection's modification time.
- All membership mutations serialize on the parent collection row inside an
  atomic transaction. This also protects initially empty collections on PostgreSQL.
  Position rewriting uses an offset above the highest current position so gaps
  cannot cause uniqueness collisions. Existing database uniqueness constraints
  still protect both work membership and positions.

## Preserved boundaries

No schema migration is needed. Existing IDs, URLs, slugs, visibility, descriptions,
annotations, membership, and stored order are preserved. Title edits keep the URL;
incorrect slugs redirect only after visibility authorization succeeds.

Collections remain curated groupings, separate from creative works and universes.
Annotations stay escaped, validated plain text (1,000 characters), rather than
catalog facts. Attribution uses the account's public username, never private email.
Homepage `FeaturedWork` editorial curation and its intentional copy remain separate
and unchanged. No editorial-collection ownership model or collaboration roles are
invented. Existing exceptional private-view permissions are preserved; those users
cannot edit another member's collection. There are no existing collection JSON/API
routes; all browser/search/mutation routes retain ownership/visibility checks.

The branch includes the completed chunk-2 connection browsing from current main.
No production database access, ingestion/enrichment runs, staging infrastructure,
merge, or deployment was performed.

## Validation

- All **102 Django tests** pass on an isolated SQLite test database, including 16
  collection tests. Regressions cover owner-only mutations, private discovery and
  search, safe text and length validation, duplicates and position constraints,
  sparse ordering, annotation persistence, membership removal without deleting a
  work, private creation, publishing restrictions, auth return, and stable URLs.
- `makemigrations --check --dry-run`: no changes. `git diff --check`: clean.
- Chromium at **1440×1000** and **390×844**: browse a public collection, log in from
  a work, create a private collection, search/add another work, annotate, move,
  and remove. Browser assertions confirm order, literal script-shaped annotation
  text, private 404s and discovery exclusion, and no horizontal overflow or JS
  errors. A mobile navigation overflow was corrected and the journeys rerun.
- Screenshots use development-only fixtures: [desktop](screenshots/chunk-3-desktop.png),
  [mobile](screenshots/chunk-3-mobile.png), and [mobile editor](screenshots/chunk-3-editor-mobile.png).
- PostgreSQL concurrent-request behavior is not exercised locally; SQLite does not
  implement row locks. Production and hosted Render flows were not tested.

## Local viewing

From the repository root with dependencies installed, explicitly avoid any inherited
production database URL:

```sh
env -u DATABASE_URL DJANGO_DEBUG=true .venv/bin/python manage.py migrate
env -u DATABASE_URL DJANGO_DEBUG=true .venv/bin/python manage.py runserver 127.0.0.1:8000
```

Open `http://127.0.0.1:8000/lists/` or a published work and choose **Add to collection**.
Use an existing development account or sign up. Private collections need no email
verification; public publishing uses the existing verification flow. No seed/import
command is required or run by this chunk. A fresh empty catalog will need existing
local fixture/catalog records to exercise work membership.
