# Field provenance (improvement chunk 5)

Work pages offer native, collapsed “Why this value?” disclosures for the primary title, public work type, and displayed date. The existing “About this connection” disclosure uses the same evidence component for accepted direct relationships. Existing relationship authorization statements also use it; no license or public-domain records exist in the implemented catalog schema. No rights determinations are added.

## Existing evidence and gaps

- `SourceRecord` retains a supplier payload and retrieval time. `ImportedWorkState` identifies supplier title/date values, but does not prove those values were selected or reviewed. Legacy matching values are labeled as recorded supplier values with missing selection history.
- `Work.date_evidence` identifies an exact date value, source URL, and sometimes a supplier statement, precision, and rank. Supplier dates keep their existing scope and precision.
- `WorkRelationship` has an assertion source, public scope note, and optional statement/retrieval metadata. Accepted status alone does not supply a dated human review. New import approvals and community relationship approvals now explicitly record their review time.
- `ContributionRevision` preserves approved corrections and previous/new values. Its public projection exposes source and review time, excluding account identities, contributor explanations, and private reviewer explanations.
- `WorkSource` and `ExternalIdentifier` remain general work links. Neither is used to backfill field citations.

The type disclosure explains the existing public-label mapping and traces a more specific display label to stored Wikidata P31/P7937 classifications when that policy applies. Recorded supplier title/date alternatives and type assertions remain visible. Different date scopes or precision and hierarchical type classifications are not automatically labeled conflicts. Distinct, recorded supporting sources with competing titles are labeled conflicting sources. Aliases are not competing primary-title claims.

## Migration and future edits

Migration `0014_contributionproposal_target_relationship_and_more` adds `FieldEvidence` for three work fields and a nullable stable relationship target on correction proposals. Existing values and source records are preserved; no data backfill or network operation runs. A conditional unique constraint allows one current evidence row per work/field, and a check constraint bounds the field set.

Work `save()` compares persisted values inside a transaction. A replacement retires current evidence, retains prior values and known legacy date/revision support, and records an uncited current value. Returning to an older string does not reactivate its citation. Explicit import writers associate only fields they actually wrote, preserving retrieval time and selection/normalization notes. Existing title repair and offline date correction writers also register their evidence.

Relationship edits retain earlier evidence in an internal `evidence_history` snapshot. Changing endpoints/type without replacement evidence invalidates the current source association. Relationship-note and attributed-statement corrections have separate source/review metadata and retained public value history. Raw archived payloads are never rendered. Relationship targets use PROTECT so deletion/duplicate-removal cannot discard a correction's target; merges that require deleting a targeted relationship must resolve that target explicitly.

Use model `save()` and `catalog.provenance.record_evidence()` for future supported-field writers. Django `QuerySet.update()`/bulk writes bypass save hooks; current bulk operations change visibility or explicit merge associations, not selected title/type/date values. The merge service retires moved field evidence as history. General value-selection policy is unchanged.

Migration `0015_merge_20261006_1851` joins the provenance and personal-library migration branches without data operations. Save hooks preserve both evidence history and library relationship/publication events. Provenance uses the current paginated, filterable connection evidence interface.

## Corrections and public rendering

Correction links include the work, field, and stable relationship ID where applicable. The form shows the current value and ID; existing verification, login, rate limits, reviewer permissions, and pending-review behavior apply. Contributors may challenge work type, direct relationship type/note, and existing attributed statements through that same workflow. Type replacements use existing catalog codes.

Evidence text is escaped by Django. Field-source links allow validated HTTP/HTTPS URLs and reject embedded credentials. Public rendering uses an allowlist rather than serializing supplier payloads, review records, or account information. Evidence is prefetched in batches; adding rows/connections does not add per-row queries. Native details/summary supports Enter/Space and ordinary tab navigation without moving focus into a modal.

## Local viewing and validation

For an existing development checkout:

```sh
DJANGO_DEBUG=true .venv/bin/python manage.py migrate
DJANGO_DEBUG=true .venv/bin/python manage.py load_demo_catalog
DJANGO_DEBUG=true .venv/bin/python manage.py runserver 127.0.0.1:8000
```

Open a work from http://127.0.0.1:8000/. Demo data is explicitly fictional. Use a local SQLite database, never a production `DATABASE_URL`.

Verification includes the full Django suite, migration drift and system checks, and Chromium checks at 1440×1000 and 390×844 against a separate synthetic-only SQLite database. Checks cover disclosures closed by default, keyboard opening, focus retained on summary, tabbing to source links, correction context surviving the login redirect, and horizontal overflow. Closed and open desktop/mobile screenshots were visually inspected. No hosted preview, staging, production deployment, imports, or crawling are part of this change.
