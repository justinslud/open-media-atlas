# Open Library cloud bulk pilot

This pilot runs extraction, validation, and staged ingestion inside **one Render one-off job**. It uses the repository's deployed image and environment, streams the three official gzip dumps, writes only the bounded extract to `/tmp`, and persists provenance, parameters, checkpoints, per-record outcomes, and its final report in PostgreSQL. It needs no workstation setup, container, dump transfer, persistent disk, S3, or always-on worker.

> Safety: launch this only from the existing **pilot/staging Render service whose `DATABASE_URL` is a non-production database**. A one-off job inherits its parent service's build, environment variables, plan, and region. Never launch it from the production web service.

## Pinned snapshot configuration

Use the three separate `latest` links on [Open Library's official dump page](https://openlibrary.org/developers/dumps). At job start, the command resolves all three redirects, requires them to identify one matching dated Internet Archive snapshot, replaces them with canonical dated URLs, and obtains each published SHA-1/SHA-256 from official Internet Archive metadata. The resolved date, URLs, and checksums are persisted before extraction. Set these environment variables on the service:

```text
OPENLIBRARY_EDITIONS_URL=https://openlibrary.org/data/ol_dump_editions_latest.txt.gz
OPENLIBRARY_WORKS_URL=https://openlibrary.org/data/ol_dump_works_latest.txt.gz
OPENLIBRARY_AUTHORS_URL=https://openlibrary.org/data/ol_dump_authors_latest.txt.gz
OPENLIBRARY_LIMIT=5000
OPENLIBRARY_MAX_RUNTIME=21600
OPENLIBRARY_MIN_FREE_MIB=512
```

Leave `OPENLIBRARY_SNAPSHOT_DATE` and the three `OPENLIBRARY_*_CHECKSUM` variables unset. Do not estimate a date. The command discovers and verifies the actual date and official checksums. You may instead set them as additional assertions; if supplied, they must exactly match official metadata or the job stops before scanning. A later resume uses the canonical pinned values already recorded on the run, so a changed `latest` snapshot cannot silently continue an older run.

## What the command does

```bash
python manage.py run_openlibrary_cloud_pilot
```

1. Resolves the three official links to one dated snapshot, verifies official metadata, then creates an `ImportRun` recording canonical URLs, checksums, selection parameters, limits, and status in Postgres.
2. Checks `/tmp` free space against `OPENLIBRARY_MIN_FREE_MIB` before network scans. The raw compressed dumps are streamed directly and never stored or unpacked. The small deterministic JSONL extract and reports alone use temporary disk.
3. Streams editions twice (selection, then up to two editions per chosen work), works once, and authors once. The configured SHA-1/SHA-256 is checked at the end of every full stream. Selection retains at most 5,000 IDs and ingestion handles one record per transaction, so memory is bounded.
4. Validates the extract checksum and count, then ingests it in the same process. New works remain drafts. Existing public works are conflicts and are not changed; supplier updates cannot overwrite a human-edited draft field.
5. Saves scan checkpoints periodically and a concise final report in `ImportRun.stats`; provenance remains in the manifest, `SourceRecord`, `ImportItem`, identifiers, and source links. Raw dumps are never put in Postgres.

`--max-runtime`/`OPENLIBRARY_MAX_RUNTIME` is a graceful runtime target, not an enforced dollar cap. Six hours on a 512 MiB instance plus database usage is the planning basis for the requested **$5–10 pilot range**; confirm the current hourly price displayed by Render before launch. Network throughput and current dump sizes dominate runtime. Raise `OPENLIBRARY_MIN_FREE_MIB` if the expected extract plus safety margin exceeds 512 MiB.

### Restart and troubleshooting behavior

The deterministic selection makes reruns idempotent. A completed ingestion item is skipped, failed items retry, source hashes suppress unchanged updates, and stable Open Library IDs prevent duplicate works/authors/releases.

Temporary storage disappears when a job ends. Therefore interrupted **dump scans restart from byte zero** and reconstruct the extract; gzip/HTTP scans have no durable byte checkpoint. Pass `--resume-run RUN_ID` in a new job to reconstruct the same checksum-matching extract and resume **ingestion** from committed `ImportItem` rows. Changed URLs, checksums, seed, limits, or runtime settings are refused for that run. The extraction checkpoints in Postgres are observability records, not byte-range resume points.

Troubleshooting modes still perform cloud extraction and validation but do not ingest:

```bash
python manage.py run_openlibrary_cloud_pilot --dry-run
python manage.py run_openlibrary_cloud_pilot --extract-only
python manage.py run_openlibrary_cloud_pilot --resume-run RUN_ID
```

The older `extract_openlibrary` and `ingest_openlibrary_extract --dry-run` commands remain available for small fixture diagnosis, but they are not the normal pilot workflow.

## Render launch, monitoring, cancellation, and review

Render's one-off-job documentation says a job uses the selected service's latest successful deploy by default and inherits its environment. In the Render dashboard:

1. Open the **non-production pilot web service** and verify its latest deploy is this commit and its `DATABASE_URL` points to the pilot database.
2. Click **Shell → New one-off job**, enter `python manage.py run_openlibrary_cloud_pilot`, select a 512 MiB instance, and click **Run job**.
3. Open that job to follow live logs. Copy the printed `run_id`. Click **Cancel job** on the job page to stop it; the current DB transaction rolls back and earlier records remain resumable.
4. Review **Catalog → Import runs**, its import items/source records, and draft works in Django admin. No promotion is part of the cloud command.

For a credential-free browser trigger, add `RENDER_API_KEY` (a narrowly scoped Render API key) and `RENDER_PILOT_SERVICE_ID` as GitHub Actions repository secrets, then click **Actions → Run Open Library cloud pilot → Run workflow**. The workflow calls Render's `POST /v1/services/{serviceId}/jobs` endpoint from GitHub; the key never enters Git or browser-side application code. Delete/rotate it after the pilot. Monitor and cancel in Render exactly as above.

## Justin's next steps

1. On the chosen Render service, set the six values shown above. Confirm which database its `DATABASE_URL` names and take/verify a recovery point if it is production.
2. Confirm the displayed price for a 512 MiB one-off job and that the job has at least `OPENLIBRARY_MIN_FREE_MIB` temporary space.
3. Deploy this commit, then click **Shell → New one-off job**, enter `python manage.py run_openlibrary_cloud_pilot`, choose 512 MiB, and click **Run job**.
4. Watch the job's live logs; use **Cancel job** there if needed.
5. Open Django admin → **Catalog → Import runs**, select the printed run ID, and review its report, failures/conflicts, source records, and draft works.
