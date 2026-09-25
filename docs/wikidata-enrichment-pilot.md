# Wikidata relationship-enrichment pilot

This is a bounded **staging** job, not a crawler. It discovers only non-deprecated inbound `P144` (“based on”) statements for the 50 pinned work entities in `data/wikidata-pilot-seeds.json`, stops at 300 related works, and fetches entity metadata in batches of 50. It does not recurse. The query and entity JSON are cached in `SourceRecord`; a rerun is identifier-based and idempotent. Public pages never call Wikidata.

## Access and semantic decisions

Checked 2026-09-25 against the official [Wikidata Query Service user manual](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual), [query limits guidance](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service/WDQS_backend_update/Blazegraph_failure_playbook), [MediaWiki API etiquette](https://www.mediawiki.org/wiki/API:Etiquette), [`wbgetentities` documentation](https://www.wikidata.org/w/api.php?action=help&modules=wbgetentities), and the [P144 property page](https://www.wikidata.org/wiki/Property:P144). The job uses one small `VALUES` SPARQL query for relationship discovery and `wbgetentities` for batches of at most 50 entities. Requests identify OMA, time out, retry transient errors and 429s with backoff/`Retry-After`, use no concurrency, pass `maxlag`, and have an overall request cap.

`P144` maps to the deliberately broad OMA term **Based on / Inspired or adapted works**. It does not map to “faithful adaptation.” Direction is derived work → source work. Rank, statement ID, property ID, qualifiers, references, entity revision and retrieval time remain on the staged proposal and, after approval, its relationship. Deprecated statements are excluded. “Wikidata asserted this” is distinct from editor acceptance, and no rights, license, or public-domain conclusion is made.

The manifest is reproducible and labels why each QID was selected. It includes individual Shakespeare plays and Sherlock Holmes works rather than characters/franchises, plus recognizable novels across periods. The API remains authoritative: missing/redirected/type-changed identifiers are reported rather than replaced by title. Exact Wikidata ID wins, then an explicit Open Library work ID; titles only produce a conflict for review. Existing records are never supplier-updated by this pilot. New works are drafts; aliases and all unsupported/richer fields remain available in raw source JSON. Work type, description, dates (with precision retained in raw JSON), original language, Open Library IDs, Wikidata links, and explicitly stated author (`P50`) or director (`P57`) credits are staged where supported.

## Run one bounded Render job

Launch only from the existing staging/pilot service whose `DATABASE_URL` you have verified is non-production. A dry run persists only its run/report:

```bash
python manage.py run_wikidata_enrichment --dry-run
```

The normal bounded job is:

```bash
python manage.py run_wikidata_enrichment --seed-limit 50 --related-limit 300 --request-limit 250 --timeout 30 --max-runtime 1800
```

From a trusted terminal (not the Render shell), launch that exact command as a Render one-off job:

```bash
curl --fail-with-body --silent --show-error \
  --request POST "https://api.render.com/v1/services/${RENDER_SERVICE_ID}/jobs" \
  --header "Authorization: Bearer ${RENDER_API_KEY}" \
  --header "Content-Type: application/json" \
  --data '{"startCommand":"python manage.py run_wikidata_enrichment --seed-limit 50 --related-limit 300 --request-limit 250 --timeout 30 --max-runtime 1800"}'
```

Logs show the run ID, limits, progress summary, and final report. `ImportRun.stats` persists seeds attempted, matched/new entities, proposed relationships, ambiguous matches, failures, skipped statements, network requests, elapsed time, truncation, and coverage limitations. A failed run retains already cached source records/items; the same command is safe to rerun, though this initial command creates a separately auditable run.

## Review and promote

1. Open **Django admin → Catalog → Import runs → RUN_ID**. Inspect each source → **Based on** → target row, evidence JSON, conflicts, failures, and the truncation/report fields.
2. Inspect draft endpoint metadata and source records. Reject questionable statements by leaving them unselected; the command accepts only explicitly named statement IDs.
3. Preview an explicit selection:

   ```bash
   python manage.py promote_wikidata_run RUN_ID --reviewer JUSTIN --statement 'Q…$…' --publish-endpoints
   ```

4. Repeat with `--confirm` only after review. Repeat `--statement` for each approved assertion. Publishing endpoints and accepting relationships happen atomically. Accepted relationships then appear in both directions on public detail pages and normal relationship counts/filters.

## Coverage and matching limitations

Coverage is whatever Wikidata currently asserts with non-deprecated `P144`; it is neither a complete adaptations list nor independent verification. The report says when the 300-row cap truncates discovery. Some adaptations use other properties, link an edition/episode/series, lack `P144`, or have ambiguous modeling, and this pilot intentionally skips them. It does not recursively crawl, merge titles, resolve conflicting identifiers, infer rights, download images, or overwrite human edits. Date precision, aliases, and unmodeled claims remain in cached source JSON. Reviewers must check entity granularity and references before approval.

## Justin's next steps

1. Deploy this commit to the existing Render pilot service and confirm its database is not production.
2. Run the dry-run one-off command and inspect the final limits/coverage report.
3. Run the normal bounded one-off job; copy its Django run ID from logs.
4. Review that run, its conflicts, every proposed statement and both endpoint records in admin.
5. Preview, then confirm, only the statement IDs Justin approves using `promote_wikidata_run`; add `--publish-endpoints` only for endpoint drafts that are ready for public display.
