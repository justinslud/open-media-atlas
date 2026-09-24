# Open Library bulk pilot runbook

This is a **pipeline pilot**, not a popularity ranking and not a completed production import. It stages at most 5,000 works and makes no rights, ownership, or adaptation assertions. Open Library's [official dump documentation](https://openlibrary.org/developers/dumps) (checked 24 September 2026) describes monthly, gzip-compressed, five-column TSV dumps and links separate editions, works, and authors files. It points to [Internet Archive's dated `ol_exports` snapshots](https://archive.org/details/ol_exports?sort=-publicdate) for historical dumps. Use three files from one dated snapshot, never three moving `latest` links.

## Selection and resource model

The extractor first scans editions and keeps the 5,000 work IDs with the lowest SHA-256 of `seed:work_id` among editions whose explicit language key is `/languages/eng`. It does **not** assume that works have a language. A fixed seed and snapshot make the sample repeatable and hashing avoids input-order bias; it is reasonably varied but is not stratified, representative, quality-weighted, or popularity-ranked. Missing/incorrect edition language data and Open Library's coverage biases remain. A translated work qualifies when an English translation edition points to it; the pipeline does not mislabel English as the work's original language.

The edition dump is scanned twice: once for bounded hash selection and once to retain up to two English editions per selected work. Works and authors are each scanned once. All scans stream gzip input; only 5,000 IDs, selected rows, and referenced authors are held in memory. Raw dumps are never loaded into PostgreSQL. The second editions scan is the deliberate tradeoff that avoids a potentially enormous disk index. Even a one-work import still scans all editions twice and all works/authors once. Malformed rows after a valid first row are counted/skipped; wrong-type, empty, invalid-gzip, and incomplete downloads are rejected. Extraction stops safely before writing a final artifact when `--max-runtime` expires, but a stopped large-file scan must restart.

The resulting `records.jsonl`, `manifest.json`, and extraction report are reusable and small. The manifest pins source URLs, snapshot date, supplied checksums, artifact SHA-256, importer version, seed, limits, and scan counts. Keep it with the artifact. The extractor checks at least 100 MiB free, but operators must compare `df -h` with the dated snapshot's actual compressed sizes before download; do not assume a Render job's temporary allowance. Download and extract on a workstation or temporary machine with enough space, then remove raw dumps.

## 1. Pin, download, and extract (outside production)

On the Internet Archive snapshot page, choose one date and copy the exact works, editions, and authors download URLs and the checksums shown in each file's metadata. Internet Archive commonly publishes MD5/SHA-1; record those in your operator notes. The downloader can enforce SHA-256, so calculate/publish SHA-256 alongside any available archive checksums. Do not substitute `latest` after choosing the date.

```bash
mkdir -p data/openlibrary-dumps data/openlibrary-extracts/2026-09-01
df -h data/openlibrary-dumps

python manage.py download_openlibrary_dump 'EDITION_SNAPSHOT_URL' data/openlibrary-dumps/editions.txt.gz --sha256 EDITION_SHA256
python manage.py download_openlibrary_dump 'WORK_SNAPSHOT_URL' data/openlibrary-dumps/works.txt.gz --sha256 WORK_SHA256
python manage.py download_openlibrary_dump 'AUTHOR_SNAPSHOT_URL' data/openlibrary-dumps/authors.txt.gz --sha256 AUTHOR_SHA256

python manage.py extract_openlibrary \
  --editions data/openlibrary-dumps/editions.txt.gz \
  --works data/openlibrary-dumps/works.txt.gz \
  --authors data/openlibrary-dumps/authors.txt.gz \
  --output data/openlibrary-extracts/2026-09-01 \
  --snapshot-date 2026-09-01 --limit 5000 --editions-per-work 2 \
  --seed oma-ol-pilot-v1 --max-runtime 21600 \
  --editions-url 'EDITION_SNAPSHOT_URL' --editions-sha256 EDITION_SHA256 \
  --works-url 'WORK_SNAPSHOT_URL' --works-sha256 WORK_SHA256 \
  --authors-url 'AUTHOR_SNAPSHOT_URL' --authors-sha256 AUTHOR_SHA256

python manage.py ingest_openlibrary_extract data/openlibrary-extracts/2026-09-01 --dry-run
tar -C data/openlibrary-extracts -czf oma-ol-extract-2026-09-01.tgz 2026-09-01
sha256sum oma-ol-extract-2026-09-01.tgz
```

Upload/download the tarball through an already approved private object store or Render job file transfer mechanism. No object-store dependency is required by the app. If no approved durable store exists, retain the archive on the operator workstation and upload it for each job. Treat temporary one-off-job files as disposable; download the `ingest-run-ID.json` report before the job ends or copy its JSON from output/admin. Never commit dumps or extracts.

## 2. Local rehearsal

```bash
DJANGO_DEBUG=true python manage.py migrate
DJANGO_DEBUG=true python manage.py ingest_openlibrary_extract data/openlibrary-extracts/2026-09-01 --dry-run
DJANGO_DEBUG=true python manage.py ingest_openlibrary_extract data/openlibrary-extracts/2026-09-01 --batch-size 50 --max-runtime 14400
DJANGO_DEBUG=true python manage.py promote_openlibrary_run RUN_ID
```

In admin, inspect **Import runs**, all conflicted/failed items, source payloads, author credits, English edition releases, and draft works. The last command is preview-only without `--confirm`.

Ingestion commits one work per short transaction. An interrupted run retains completed items and its manifest; retain the exact extract and run `--resume-run RUN_ID`. Failed items retry, completed items skip, and a different artifact checksum is refused. New records remain drafts. Existing public records are never changed: supplier differences become conflicts. Draft imported fields update only if blank or still equal their prior supplier value; missing source fields do not erase richer values. Work/author/edition source keys, constraints, and run-item uniqueness make reruns idempotent; title alone is never a work match. Same-ID ambiguity is reported rather than merged. Community-approved/human edits therefore remain protected.

## 3. Render production sequence

Render's [one-off job documentation](https://render.com/docs/one-off-jobs) (checked 24 September 2026) says jobs use a service's built image/configuration and environment variables. Consequently this job receives the production `DATABASE_URL`: it is **not** an isolated database. It also cannot rely on the web service's persistent disk, and temporary job files do not survive a later job.

1. Merge/deploy this code and confirm the deploy ran migrations. In the Render dashboard open **open-media-atlas-db → Recovery** and verify point-in-time recovery is enabled and its recovery window includes the current time. Do this immediately before mutations; a green web deploy is not a backup check.
2. Open **New + → One-off Job**, select the repository/branch or the deployed environment for **open-media-atlas**, and choose the same commit/image as the healthy web service. Confirm `DATABASE_URL` is inherited. Choose **Starter (512 MB)** initially: extraction is intentionally performed elsewhere, while the bounded JSONL ingestion retains one record at a time. Do not attach or rely on the web persistent disk.
3. Make the extract available in that job (for example, a short-lived authenticated download from an approved private store), unpack it under `/tmp/oma-extract`, and use this exact start command for validation:

   ```bash
   python manage.py ingest_openlibrary_extract /tmp/oma-extract --dry-run
   ```

4. Inspect the checksum/count output. Start a second one-off job from the **same deployed commit**, provide the same extract, and use:

   ```bash
   python manage.py ingest_openlibrary_extract /tmp/oma-extract --batch-size 50 --max-runtime 14400 --report /tmp/ingest-report.json
   ```

5. Save the printed run ID and report/log output. If it stopped gracefully, start another identical job, restore the **same checksum-matching extract**, and run:

   ```bash
   python manage.py ingest_openlibrary_extract /tmp/oma-extract --resume-run RUN_ID --batch-size 50 --max-runtime 14400 --report /tmp/ingest-report.json
   ```

6. Inspect the run and drafts in Django admin. Resolve every conflict/failure; spot-check source attribution, authors, editions, translations, and public search (drafts must not appear). Preview promotion in another one-off job:

   ```bash
   python manage.py promote_openlibrary_run RUN_ID
   ```

7. Only after explicit editorial approval, publish the new records:

   ```bash
   python manage.py promote_openlibrary_run RUN_ID --confirm --limit 5000
   ```

The four-hour `--max-runtime 14400` is a conservative operational limit, not a platform or billing cap. At current dashboard rates, confirm the displayed Starter hourly price before launching; two short ingestion jobs should be comfortably inside the requested **$5–10 estimate**, but Render does not enforce that budget. Watch the live job logs and the Billing page. To stop spending or halt unexpected behavior, open the running job in the dashboard and click **Cancel job**; cancellation may interrupt the current one-record transaction, which rolls back, while prior items survive. Do not create an always-on worker.

## Reports and limitations

Extraction reports compressed bytes/records scanned, eligible editions, selected/written works, malformed rows, elapsed extraction time, free disk before the run, and peak RSS. Ingestion reports created, updated, unchanged, skipped-on-resume, conflicted, failed, elapsed database time, peak RSS, and PostgreSQL database bytes before/after (including indexes via `pg_database_size`; `null` on SQLite). Paths appear in the manifest/report and progress logs print every batch.

Remaining pilot limits: it does not process redirects/deletes, infer original language, resolve translators, attach rights/public-domain claims, create adaptations, rank popularity, or update public records automatically. Author identity uses Open Library author keys; releases use edition keys. Extraction itself is restart-only, and reuse requires retaining the complete extract directory. Review and promotion remain intentionally explicit.

## Justin's next steps

1. Pick one dated Internet Archive snapshot; record its three exact URLs and published checksums.
2. Run the download/extraction commands on a machine whose `df -h` result safely exceeds the displayed dump sizes, then retain the checksum-verified extract archive.
3. Merge and deploy this PR; immediately verify the production database recovery window in Render.
4. Launch the dry-run one-off job, then the staged-ingestion job, using the same deployed commit and extract.
5. Inspect the run/drafts and conflicts in admin. Run promotion preview, then use `--confirm` only if the review is satisfactory.
