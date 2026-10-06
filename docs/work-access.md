# Work access (OMA chunk 6)

Work pages now lead to a compact Read, Watch, or Listen section (Access options for other media). Direct full-work and excerpt destinations come first, followed by borrow/buy/rent/subscription offers. Catalog and unclassified destinations live in a separate collapsed reference group; external search links always say “Search [provider]” and explicitly do not verify availability. The header action jumps to this section instead of presenting a catalog source as an access option.

## Data and provenance

Inspection of the existing schema found only general `WorkSource` citations, external identifiers, and Open Library edition keys. Those links stay in Sources and version releases; they are not converted into available copies. Source URLs now use chunk 5's `safe_url` validation before public rendering, and the blanket Open Library domain suppression is removed so existing references remain clickable.

`AccessLink` adds provider, URL, a small purpose/access category, optional version/release target, explicit unresolved scope, language, region, conditions, supporting source, content/offer check date, review time, and an active flag. Blank metadata is unknown. Multiple links from one provider are allowed for different editions or offers. A release/version must belong to the work, and a selected release must match its selected version. Without a known target/scope, the display says “Edition / version not specified.” Adaptation links belong to that adaptation's work; they are never inherited from connected works.

A description's editorial review time and its content/offer check date are separate. HTTP success is insufficient for either an access claim or a content check date. No page checker, server-side URL fetch, paid API, crawler, ingestion, or bulk link check is added. Rights, authorization, official status, free access, and public-domain status are never inferred from these links.

## Existing review process

“About this link” reuses chunk 5's public evidence component and URL validator, excluding private contributor/reviewer text. Each recorded link has a report/replacement action. Verified members submit access proposals through the existing `ContributionProposal` admin review, private My contributions page, and owner-only clarification/resubmission flow. Login preserves the work/link context. The existing `catalog.review_contributionproposal` permission is required for approval/rejection; approval revalidates URLs and entity scope.

Proposals preserve the original submitted URL, payload, explanation, supporting source, and review outcome. Replacements snapshot the previous link including its supporting source/review time into `ContributionRevision`; conflicts require explicit reconciliation. Approved problem reports deactivate the link without deleting it or its proposals. AccessLink admin is read-only: publication goes through proposal review. Existing general reference/source maintenance remains editorial; this feature does not reinterpret or migrate those sources into access offers.

## Migration and deployment

`0016_alter_contributionproposal_kind_and_more` adds AccessLink, a nullable protected proposal target, and the access proposal/revision kind. It follows chunk 5's merged migration graph. It is additive and has no data backfill, fetching, ingestion, or startup action. Existing sources/identifiers/versions and rights evidence are preserved. Run `python manage.py migrate` with the normal production deployment when separately authorized. No staging or hosting infrastructure is introduced, and this PR does not deploy.

Existing records will usually have no known access links until reviewed suggestions are added. For known titles without a specific access offer, ordinary text works get a clearly labelled Open Library search; other media get an Internet Archive search. These are title queries, not resolved matches. Synthetic demo works do not generate external searches automatically, and unknown titles do not get invented search terms. Region and offer metadata are editorial snapshots; no live availability service exists. The Version schema has no structured media/access entitlement model; unresolved differences must be stated in scope/conditions rather than inferred.

## Inspect locally with isolated fixtures

Use an empty disposable SQLite database. The fixture has fixed IDs and fictional facts; do not load it into an existing or production database. From the repository root:

```sh
mkdir -p work
cat > work/access_settings.py <<'PY'
from oma.settings import *
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "work/access-fixtures.sqlite3"}}
PY
env -u DATABASE_URL DJANGO_DEBUG=true DJANGO_SETTINGS_MODULE=work.access_settings .venv/bin/python manage.py migrate
env -u DATABASE_URL DJANGO_DEBUG=true DJANGO_SETTINGS_MODULE=work.access_settings .venv/bin/python manage.py loaddata access_preview
env -u DATABASE_URL DJANGO_DEBUG=true DJANGO_SETTINGS_MODULE=work.access_settings .venv/bin/python manage.py runserver 127.0.0.1:8000
```

- Book with direct access and a translation-specific borrow offer: `/works/1/the-paper-harbor/`.
- Film with trailer and restricted rental: `/works/2/harbor-at-night/`.
- Audio with subscription and separate catalog entry: `/works/3/harbor-sounds/`.
- No specific access offer, with explicitly labelled search: `/works/4/the-unrecorded-journey/`.
- Report/replacement form: `/works/1/suggest-access/?link=1` (login; verified email required to submit).

## Verification

- Full Django suite: 163 tests pass. Access tests cover access/catalog/search distinctions; unknown availability and metadata; media headings; version/release scope and cross-work rejection; no source/domain/HTTP-based promotion; escaping and unsafe URL rejection; authenticated/verified submission; reviewer permission; conflicts; deactivation with retained history; clarification and owner-only resubmission; hidden work and mismatched target rejection.
- Django system check, migration drift check, and `git diff --check` pass.
- Chromium checked all four isolated synthetic pages at 1440×1000 and 390×844: no horizontal overflow or JavaScript page errors. Native disclosures open with Enter and retain focus; Tab reaches the supporting source. Report links preserve their target through login, and the prefilled report form fits mobile. Screenshots were visually inspected.
- The existing suite's importer tests use mocked/in-memory fixture inputs; no live ingestion or production writes were run.

Screenshots: [book desktop](screenshots/chunk-6-book-desktop.png), [book mobile](screenshots/chunk-6-book-mobile.png), [missing access mobile](screenshots/chunk-6-missing-mobile.png), [report mobile](screenshots/chunk-6-report-mobile.png).
