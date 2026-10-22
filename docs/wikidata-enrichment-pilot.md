# Wikidata relationship-enrichment pilot

This is a bounded **staging** job, not a crawler. It discovers only non-deprecated inbound `P144` (“based on”) statements for the pinned work entities in `data/wikidata-pilot-seeds.json`, stops at the configured related-work cap (default 1,000; safety ceiling 5,000), and fetches entity metadata in batches of 50. It does not recurse. The query and entity JSON are cached in `SourceRecord`; a rerun is identifier-based and idempotent. Public pages never call Wikidata.

## Access and semantic decisions

Checked 2026-09-25 against the official [Wikidata Query Service user manual](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual), [query limits guidance](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service/WDQS_backend_update/Blazegraph_failure_playbook), [MediaWiki API etiquette](https://www.mediawiki.org/wiki/API:Etiquette), [`wbgetentities` documentation](https://www.wikidata.org/w/api.php?action=help&modules=wbgetentities), and the [P144 property page](https://www.wikidata.org/wiki/Property:P144). The job uses one small `VALUES` SPARQL query for relationship discovery and `wbgetentities` for batches of at most 50 entities. Requests identify OMA, time out, retry transient errors and 429s with backoff/`Retry-After`, use no concurrency, pass `maxlag`, and have an overall request cap.

`P144` maps to the deliberately broad OMA term **Based on / Works based on this**. It does not map to “faithful adaptation.” Direction is derived work → source work. Rank, statement ID, property ID, qualifiers, references, entity revision and retrieval time remain on the staged proposal and, after approval, its relationship. Deprecated statements are excluded. “Wikidata asserted this” is distinct from editor acceptance, and no rights, license, or public-domain conclusion is made.

The manifest is reproducible and labels why each QID was selected. It includes individual Shakespeare plays and Sherlock Holmes works rather than characters/franchises, plus recognizable novels across periods. The API remains authoritative: missing/redirected/type-changed identifiers are reported rather than replaced by title. Exact Wikidata ID wins, then an explicit Open Library work ID; titles only produce a conflict for review. Existing records are not supplier-updated by the discovery path. The explicit candidate path may refresh type, a first-performance date, or a `P1476` title only for a draft index record with the same exact QID and a generic type. New works are drafts; aliases and all unsupported/richer fields remain available in raw source JSON. Work type, description, dates (with precision retained in raw JSON), original language, Open Library IDs, Wikidata links, and explicitly stated author (`P50`) or director (`P57`) credits are staged where supported.

## Run one bounded Render job

Launch only from the existing staging/pilot service whose `DATABASE_URL` you have verified is non-production. A dry run persists only its run/report:

```bash
python manage.py run_wikidata_enrichment --dry-run
```

The normal bounded job is:

```bash
python manage.py run_wikidata_enrichment --seed-limit 50 --related-limit 1000 --request-limit 500 --timeout 30 --max-runtime 1800
```

From a trusted terminal (not the Render shell), launch that exact command as a Render one-off job:

```bash
curl --fail-with-body --silent --show-error \
  --request POST "https://api.render.com/v1/services/${RENDER_SERVICE_ID}/jobs" \
  --header "Authorization: Bearer ${RENDER_API_KEY}" \
  --header "Content-Type: application/json" \
  --data '{"startCommand":"python manage.py run_wikidata_enrichment --seed-limit 50 --related-limit 1000 --request-limit 500 --timeout 30 --max-runtime 1800"}'
```

Logs show the run ID, limits, progress summary, and final report. `ImportRun.stats` persists seeds attempted, matched/new entities, proposed relationships, ambiguous matches, failures, skipped statements, network requests, elapsed time, truncation, and coverage limitations. A failed run retains already cached source records/items; the same command is safe to rerun, though this initial command creates a separately auditable run.

## Candidate-manifest mode

The stage slice used an explicit candidate JSON file to avoid depending on Wikidata Query Service during its outage. It is the same staging pipeline, not a separate manual import:

```bash
python manage.py run_wikidata_enrichment \
  --manifest data/wikidata-golden-20.json \
  --candidates data/stage-adaptations-2026-10-22.json \
  --seed-limit 20 --related-limit 20 --request-limit 60
```

The candidate manifest supplies exact QIDs, an expected seed, and optional expected type/year for automated checks. The importer still fetches each entity with `wbgetentities` and requires a non-deprecated `P144` claim to a selected seed. A candidate with no such claim is recorded as unmatched; no edge is inferred from a title.

Stage-specific type mappings are now:

- `Q1344` → `opera`
- `Q2743` → `musical`
- `Q15079786` → `ballet`
- `Q25379` → `play`

When multiple stage classifications exist, precedence is opera, musical, ballet, play. Stage dates are selected with the medium-aware order (`P1191` first performance before `P571` inception) at staging time.

Title collisions are allowed only for explicit candidate QIDs, so an adaptation that shares a title with its source still becomes a separate draft. Exact-ID candidate matches can refresh a generic draft’s type/date/title; public and editorial records are untouched. Reruns skip an existing pending or approved proposal for the same statement and edge, so they do not multiply the review queue.

### Generating the candidate bundle

`discover_wikidata_stage_candidates` queries non-deprecated inbound `P144` for opera, musical, and ballet types, fetches the candidates, excludes exact QIDs already in the catalog, and writes a candidate manifest. It stages nothing:

```bash
python manage.py discover_wikidata_stage_candidates \
  --manifest data/wikidata-golden-20.json \
  --output data/stage-candidates-discovered-2026-10-22.json \
  --limit 30
```

The output records expected type, expected year, date property, and whether the QID already exists. Feed it to `run_wikidata_enrichment --candidates` only after reviewing the bundle. This is the bridge to a larger automated process: discovery emits candidates, staging remains bounded, and approval stays separate.

## Review and promote

1. Open **Django admin → Catalog → Import runs → RUN_ID**. Inspect each source → **Based on** → target row, evidence JSON, conflicts, failures, and the truncation/report fields.
2. Inspect draft endpoint metadata and source records. Reject questionable statements by leaving them unselected; the command accepts only explicitly named statement IDs.
3. Preview an explicit selection:

   ```bash
   python manage.py promote_wikidata_run RUN_ID --reviewer JUSTIN --statement 'Q…$…' --publish-endpoints
   ```

4. Repeat with `--confirm` only after review. Repeat `--statement` for each approved assertion. Publishing endpoints and accepting relationships happen atomically. Accepted relationships then appear in both directions on public detail pages and normal relationship counts/filters.

## Coverage and matching limitations

Coverage is whatever Wikidata currently asserts with non-deprecated `P144`; it is neither a complete adaptations list nor independent verification. The report says when the configured row cap truncates discovery. Some adaptations use other properties, link an edition/episode/series, lack `P144`, or have ambiguous modeling, and this pilot intentionally skips them. It does not recursively crawl, merge titles, resolve conflicting identifiers, infer rights, download images, or overwrite human edits. Date precision, aliases, and unmodeled claims remain in cached source JSON. Reviewers must check entity granularity and references before approval.

## Justin's next steps

1. Deploy this commit to the existing Render pilot service and confirm its database is not production.
2. Run the dry-run one-off command and inspect the final limits/coverage report.
3. Run the normal bounded one-off job; copy its Django run ID from logs.
4. Review that run, its conflicts, every proposed statement and both endpoint records in admin.
5. Preview, then confirm, only the statement IDs Justin approves using `promote_wikidata_run`; add `--publish-endpoints` only for endpoint drafts that are ready for public display.

## Repair unresolved titles already in the catalog

The title repair command extends the same identifier-based Wikidata machinery and `ImportRun`/`ImportItem` tracking. It reads `P1476`, labels in all returned languages, `P345` IMDb IDs, and exact Wikidata sitelinks. English is preferred when Wikidata supplies it; otherwise the sourced monolingual/original or available-language value is retained with its language in the import item and source note. An exact Wikipedia sitelink is fetched for supplemental metadata and stored as a cited `SourceRecord`/`WorkSource`. The job never uses name-only matching, overwrites a non-imported editorial title, merges an IMDb conflict, removes a sparse work, or changes relationship review/confidence.

For the reported example, the identifier mapping was checked directly: [Wikidata `Q3235021`](https://www.wikidata.org/wiki/Q3235021) supplies the French label *Les Quatre Mousquetaires*, [IMDb `P345` value `tt0258903`](https://www.imdb.com/title/tt0258903/), a 1934 date, and Gaston Schoukens as director. Its [exact French Wikipedia sitelink](https://fr.wikipedia.org/wiki/Les_Quatre_Mousquetaires) identifies the same Belgian film. The similarly named 1934 German film is a different work and IMDb identifier, so it must not be merged by English-name similarity.

First establish the target. With no `DATABASE_URL`, debug mode targets local SQLite; deployed jobs use the PostgreSQL database named by `DATABASE_URL`:

```bash
DJANGO_DEBUG=true python manage.py shell -c 'from django.db import connection; print(connection.vendor, connection.settings_dict["NAME"])'
```

Then run the one-time bounded job (the command also prints the selected database before doing work):

```bash
python manage.py enrich_wikidata_titles --limit 5000 --request-limit 500 --timeout 30
```

If a platform runtime limit requires chunks, use the reported `last_work_id` as the next checkpoint:

```bash
python manage.py enrich_wikidata_titles --limit 250 --after-id LAST_WORK_ID --request-limit 100 --timeout 30
```

Unresolved items remain linked to their relationships and are recorded as failed enrichment items for a later retry. Public rendering labels them **Title pending enrichment** rather than treating a QID as a title; their Wikidata identifier remains available in Sources.
