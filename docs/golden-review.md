# Golden 20 review guide

Local server: <http://127.0.0.1:8000/> · admin: <http://127.0.0.1:8000/admin/>

Sign in with the local `admin` account. These paths are local research views only.

## 1. Golden seeds

<http://127.0.0.1:8000/admin/catalog/work/?depth=editorial&is_demo__exact=0>

- Click a title to inspect the record.
- `Image preview` shows the Commons file, license, and attribution.
- `Dates` shows the displayed date plus `date_evidence` (property, candidates, selection rule).
- `Public page` opens the reader-facing page.
- Filter `date = No year` to inspect missing dates.

## 2. Accepted edges

<http://127.0.0.1:8000/admin/catalog/workrelationship/?review_status=accepted&golden=yes>

- Each row is one accepted relationship. The arrow runs from `From work` to `To work`.
- Both endpoints and `Inspect edge` are clickable.
- Open a row to read `Evidence JSON`, the source, and the exact statement.
- Use the endpoint links to inspect either work before judging the edge.
- Change `Review status` only after checking the evidence. Do not approve in bulk.

Filter by relationship type, source, or golden endpoint. Use the public page timeline for the reader-facing version.

## 3. Pending proposals for the golden set

<http://127.0.0.1:8000/admin/catalog/importrelationshipproposal/?status=pending&golden=yes>

- This is the review queue, not a to-do list that must be cleared.
- Current state: **161 pending proposals, all amber**, after the general-discovery pass. **38** have an undated endpoint.
- Use `triage_proposals` for the rolling green/amber/red classification; review exception groups, not every row.
- Leave weak or obscure proposals pending. Do not use the bulk action on the whole queue.

### Stage slice review queues

Stage slice A (run 10) is approved. Nine dated endpoints are public; the undated Dorian Gray opera remains a draft. The ten accepted edges are visible from their seed pages.

<http://127.0.0.1:8000/admin/catalog/importrelationshipproposal/?status=pending&run__id__exact=11>

Stage slice B (run 11) is approved. All five dated ballet endpoints are public.

The television slice (runs 5 and 7) is approved: 14 dated endpoints are public, and the undated `Daai Bo Fuk` remains a draft.

## 4. Dates

<http://127.0.0.1:8000/admin/catalog/work/?visibility=public&has_date=no>

Public works: **424**, **0 without a year**. The two year-only records are now displayed but explicitly marked unverified:

- `Midsummer Mechanicals` (6085), 2022
- `The Picture of Dorian Gray (Broadway, 2025)` (6160), 2025

The public pages show `Date (meaning unverified): 2022` / `2025`; the raw year was preserved and only the display text/evidence was completed.

### Current recovery rules

`backfill_wikidata_dates` now uses cached Wikidata claims in medium-aware order:

- stage: `P1191` first performance, `P1619` opening, then `P577`, `P580`, `P585`, `P571`
- screen/audio: `P577`, `P580`, `P1619`, `P2754` production, `P10135` recording, `P585`, `P571`
- text: `P577`, `P580`, `P585`, `P571`

`P582` end dates are retained as evidence but are **not** used as a start date. When several assertions exist, the earliest is selected and every candidate is kept in `date_evidence`.

A trailing parenthetical title year is a last-resort fallback only when a Wikidata record exists. It is marked `meaning_unverified`; ranges and multiple years are rejected.

```bash
.venv/bin/python manage.py backfill_wikidata_dates --scope all
.venv/bin/python manage.py backfill_wikidata_dates --scope all --confirm
.venv/bin/python manage.py backfill_wikidata_dates --scope public --complete-year-only --confirm
```

### Open foreign performing-arts sources

`import_performing_arts_dates` fills production years from two permissive sources:

- **IDU** (Arts and Theatre Institute, Czechia), `P12930`: CC BY 4.0, earliest documented IDU production premiere.
- **SPAP / performing-arts.ch** (SAPA Foundation, Switzerland), `P8974`: CC0, earliest SPARQL performance season.

```bash
.venv/bin/python manage.py import_performing_arts_dates --source all
.venv/bin/python manage.py import_performing_arts_dates --source all --confirm
```

This filled 18 foreign theatre works. `date_kind` is `production`, not `first_performance`, because an early Czech or Swiss production is not necessarily the work's world premiere.

### Wikipedia infobox dates

`backfill_wikipedia_dates` is a conservative tertiary-source pass. It reads only explicit infobox date fields, never article prose, and stores the exact revision it used.

Policy:

- Accepted fields are explicit release, publication, premiere, first-performance, first-air, opening, production, and creation fields.
- The earliest candidate is selected; all candidates are retained in `date_evidence`.
- The result is marked `meaning_unverified` and displays as `Date (meaning unverified)`.
- A `SourceRecord` stores the page title, language, revision ID, revision timestamp, revision URL, CC BY-SA 4.0 attribution, parsed candidates, and selected infobox context.
- No Wikipedia images or article prose are copied.
- English is preferred, then German, French, Italian, Spanish, Portuguese, Russian, Polish, Czech, and other sitelinks.
- The parser handles `{{Start date}}`, `{{Film date}}`, month-name dates such as `December 5, 2012`, `productions` years, German `EJahr` as `inception`, and publication ranges.
- Wikipedia API 429s are handled with retries and a configurable delay. Retry specific works with `--ids`.

```bash
.venv/bin/python manage.py backfill_wikipedia_dates --scope pending --attempts 2 --delay 3.5
.venv/bin/python manage.py backfill_wikipedia_dates --scope pending --attempts 2 --delay 3.5 --confirm
.venv/bin/python manage.py backfill_wikipedia_dates --scope pending --ids 6108,6062,6063 --delay 10 --confirm
```

Review filter:

<http://127.0.0.1:8000/admin/catalog/work/?wikipedia_date=yes>

The filtered work list now shows a **Date detail** column with the date text, date kind, and an `unverified` marker. This filled **19 works** and created **19 Wikipedia `SourceRecord`s**. Examples:

- `A Boy Scout Around the World` (6207), 1928, `publication`
- `Bumbug the Musical` (6175), 2012-12-05, `first_performance`
- `Karmma Calling` (6108), 2024-01-26, `first_release`
- `The Bridgerton Series` (6062), 2000, `publication` (earliest in a 2000–2006 range)
- `The Moor's Pavane` (6482), 1949-08-17, `first_performance`

Review these three specifically before treating the set as settled:

- `Land of Oz` (6390), 1970: theme-park opening recorded as `release`
- `Absurda Comica oder Herr Peter Squenz` (6307), 1657: German `EJahr` recorded as `inception`
- `The Bridgerton Series` (6062), 2000: first book in a publication range, not a single edition date

### Remaining pending dates

Pending proposals with an undated endpoint: **38 of 161**. Stage slice A’s Dorian Gray opera and the television `Daai Bo Fuk` are approved but remain drafts because they have no date; stage slice B is fully dated.

- The 38 include two new discovery rows with no date claim: `Frankenstein` (6582, television series) and `Hamlet: For the Love of Ophelia` (6561, film).
- Many undated rows still have a Wikipedia sitelink, but no usable machine-readable date field was found in the permissive passes.
- No permissive general film database was found. IMDb, TMDB, ČSFD, Kinopoisk, Douban, Trakt, Letterboxd, TheTVDB, IBDB, Goodreads, EIDR, and LUMIERE are treated as restricted; do not scrape them.
- The regenerated review list is `docs/missing-dates-pending-2026-10-22.csv` and `.json` (38 rows; it excludes approved-but-draft records).

Regenerate it with:

```bash
.venv/bin/python manage.py report_missing_dates --scope pending --format csv \
  --output docs/missing-dates-pending-2026-10-22.csv
```

### Admin shortcut

<http://127.0.0.1:8000/admin/catalog/importrelationshipproposal/?status=pending&undated_endpoint=yes>

Use the `endpoint date` filter to isolate proposals with an undated endpoint. Do not bulk-approve the filtered queue. The CSV is for deciding which source to pursue next, not for auto-promoting works.


## 5. Reading links

Open any golden book's public page and use the **Read** section.

- 12 Project Gutenberg full-text links, from exact Wikidata `P2034` IDs.
- 20 Open Library catalog links, from exact `P648` work IDs.
- Links record the edition uncertainty and US public-domain caveat.

## 6. Adaptation images

Adaptation records now use a Commons `P18` image only when the cached Wikidata entity has one. 21 of 404 public adaptations have one; the rest keep the typographic placeholder. These are free Commons files, not IMDb or TMDB artwork and not guaranteed posters.

## 7. Timeline

Public pages now show an **accepted connection timeline** at `#timeline`, earliest year first, with undated connections counted separately. The detailed connection list and evidence are a collapsible drill-down below it.

## 8. Stage slice A — opera, musical, ballet

The candidate manifest is `data/stage-adaptations-2026-10-22.json`: ten exact Wikidata QIDs, each with a non-deprecated `P144` claim to one golden seed. This is a probe, not a second golden set. The generated review snapshot is `docs/stage-slice-2026-10-22.json`.

### Result

- 10 candidates staged; 9 new draft works and 1 existing draft corrected (`Roméo et Juliette`, 6447).
- 10 proposals approved after review; no bulk approval.
- 9 of 10 have a date. Nine dated endpoints are public; Dorian Gray opera remains a draft.
- 8 of 10 have a licensed Commons `P18` image; Alice ballet and Dorian Gray opera have no `P18`.
- All candidate checks passed: expected type and year match for every dated work.

| Work | Type | Date | Kind | Seed |
| --- | --- | --- | --- | --- |
| Otello | opera | 1887-02-05 | first_performance | Othello |
| Roméo et Juliette | opera | 1867-04-27 | first_performance | Romeo and Juliet |
| Romeo and Juliet (Prokofiev) | ballet | 1938-12-30 | first_performance | Romeo and Juliet |
| Hamlet (Thomas) | opera | 1868-03-09 | first_performance | Hamlet |
| A Midsummer Night's Dream (Britten) | opera | 1960-06-11 | first_performance | A Midsummer Night's Dream |
| Les Misérables | musical | 1980-09 | first_performance | Les Misérables |
| The Count of Monte Cristo | musical | 2009 | publication | The Count of Monte Cristo |
| The Wizard of Oz (1902) | musical | 1902 | publication | The Wonderful Wizard of Oz |
| Alice's Adventures in Wonderland (Wheeldon) | ballet | 2011-02-28 | first_performance | Alice's Adventures in Wonderland |
| The Picture of Dorian Gray (Liebermann) | opera | — | unknown | The Picture of Dorian Gray |

### Exceptions to review

- **Dorian Gray opera (6505)** has no Wikidata date and no machine-readable infobox date. Its Wikipedia article gives the 8 May 1996 premiere in prose; that is deliberately not scraped.
- **The Count of Monte Cristo (6500)** and **The Wizard of Oz (6501)** have only a year-level `P577` claim. The date is usable as a year, but it is not evidence of a world premiere.
- **Alice ballet (6502)** and **Dorian Gray opera (6505)** have no Commons `P18`; they keep the placeholder.

### Pipeline rule learned

The reusable change is the `--candidates` path on `run_wikidata_enrichment`:

```bash
.venv/bin/python manage.py run_wikidata_enrichment \
  --manifest data/wikidata-golden-20.json \
  --candidates data/stage-adaptations-2026-10-22.json \
  --seed-limit 20 --related-limit 20 --request-limit 60
```

- A candidate list bypasses Wikidata Query Service discovery, but it still requires an exact non-deprecated `P144` claim. It never infers an edge from a title.
- Stage-specific `P31`/`P7937` values now map to `opera` (`Q1344`), `musical` (`Q2743`), and `ballet` (`Q15079786`). When a musical is also classified as a play, the stage precedence picks musical.
- Stage dates use the medium-aware order at staging time, so `P1191` first performance wins over an earlier `P571` inception claim.
- Title collisions are allowed only for an explicit candidate QID. Adaptations that share a title with their source still become separate works; title-only matches remain conflicts.
- An exact candidate QID may refresh a generic `creative-work` draft with the specific stage type and a first-performance date. Existing public/editorial records are not mutated.
- `P1476` is preferred over an English label, which corrected `Roméo et Juliete` to `Roméo et Juliette`.
- Reruns skip an existing pending or approved proposal for the same statement and edge, so repeated candidate imports do not multiply the review queue.
- The same path can be fed by an automated discovery step; the candidate list is the interface, not a hand-entered row.

### Stage slice B — automated discovery

`discover_wikidata_stage_candidates` now turns the golden seed manifest into a candidate bundle:

```bash
.venv/bin/python manage.py discover_wikidata_stage_candidates \
  --manifest data/wikidata-golden-20.json \
  --output data/stage-candidates-discovered-2026-10-22.json \
  --limit 30
```

It queries non-deprecated inbound `P144` for opera, musical, and ballet types, fetches the candidate entities, excludes exact QIDs already in the catalog, and writes expected type/year plus the date property. It creates no works and no proposals.

This found **5 new ballets**, staged as run 11. All 5 have dates and are now approved and public; none has a Commons `P18`.

| Work | ID | Date | Kind | Seed |
|---|---:|---|---|---|
| Cesta kolem světa za 80 dní | 6508 | 1962 | production | Around the World in Eighty Days |
| Mauglí | 6509 | 1996 | production | The Jungle Book |
| A Midsummer Night's Dream | 6510 | 1962-01-17 | first_performance | A Midsummer Night's Dream |
| Dorian Gray | 6511 | 2008-08 | first_performance | The Picture of Dorian Gray |
| Othello | 6512 | 1998-06-02 | release | Othello |

## 9. General candidate discovery — 2026-10-22

Generalized the stage-only discovery probe into a bounded all-media feed. It still writes only a candidate manifest; staging and triage remain separate reviewed steps.

```bash
.venv/bin/python manage.py discover_wikidata_candidates \
  --manifest data/wikidata-golden-20.json \
  --output data/wikidata-candidates-discovered-2026-10-22.json \
  --types all --limit 100 --request-limit 30

.venv/bin/python manage.py run_wikidata_enrichment \
  --candidates data/wikidata-candidates-discovered-2026-10-22.json

.venv/bin/python manage.py triage_proposals --output docs/proposal-triage-latest.json
.venv/bin/python manage.py triage_proposals --output docs/proposal-triage-latest.json --confirm
```

The query selects non-deprecated inbound `P144` for the golden seeds, restricts `P31` to supported specific types, and does not traverse recursively. The manifest is capped at 100 rows and is currently **truncated**, so more candidates remain available by raising `--limit` or adding seeds.

### Applied result

- 100 candidates staged in run 13: 100 proposals, 0 ambiguous matches after the date fix.
- Triage: **96 green, 4 amber, 0 red**.
- 96 proposals approved and 96 works published.
- Public state: **424 non-demo works, 411 accepted edges, 0 public works without a year**.
- Pending: **161 proposals, all amber**; 38 have an undated endpoint.
- Candidate mix: film 86, television series 8, video game 4, album 1, television program 1.

### New amber rows

| Work | ID | Reason |
|---|---:|---|
| Alice in Wonderland | 6559 | no Wikipedia sitelink |
| Frankenstein | 6582 | no year, date unverified, title collision |
| Frankenstein | 6632 | no Wikipedia sitelink |
| Hamlet: For the Love of Ophelia | 6561 | no year, date unverified, no sitelink |

### Pipeline changes

- `catalog/candidate_discovery.py` now holds the shared candidate-row builder; the stage command imports it instead of keeping a private copy.
- `discover_wikidata_candidates` supports `--types` (public type codes or `all`), `--limit`, `--request-limit`, `--manifest`, `--output`, and `--include-existing`.
- Staging now uses the same medium-aware date selector as discovery for every medium, not only stage. This recovered years for candidates whose Wikidata entity has several release assertions.
- Title collisions are amber only when the adaptation and source share a type, share a year, or lack a year. An eponymous adaptation with a distinct type and year is green with an `eponymous_title` warning. Exact `P144`, QID, date, and sitelink remain required.
- Discovery remains CC0 Wikidata-only for identity and edges. No restricted sites are scraped and no rights are inferred from credits.

Exceptions:

- IDU dates for `Cesta kolem světa` and `Mauglí` are documented local productions, not proven world premieres.
- `Othello` comes from a Wikipedia infobox `released` field, so it is marked `release`, not `first_performance`.
- No candidate has a Commons image; all keep placeholders.

## 9. Television slice — 2026-10-22

The pending television proposals from the golden runs form a bounded next slice. No new crawling was needed: each edge already has an exact, non-deprecated Wikidata `P144` statement and a `based-on` relationship type.

### Result

- **15 proposals reviewed**: 14 dated endpoints published, 1 undated endpoint approved but kept draft.
- Date order and exact-`P144` checks passed for every dated candidate.
- Only `El Conde: amor y honor` has a Commons `P18`; the other 13 public TV works keep placeholders.
- Public television works: **16** (2 older public records plus 14 from this slice).
- Review snapshot: `docs/tv-slice-2026-10-22.json`.

| Work | ID | Date | Kind | Seed |
|---|---:|---|---|---|
| A Infância de Romeu e Julieta | 6079 | 2023-05-08 | release | Romeo and Juliet |
| Around the World in 20 Years | 6350 | 2008 | publication | Around the World in Eighty Days |
| De vier dochters Bennet | 6389 | 1961 | publication | Pride and Prejudice |
| El Conde: amor y honor | 6065 | 2024-07-01 | release | The Count of Monte Cristo |
| Ezel | 6441 | 2009-09-28 | release | The Count of Monte Cristo |
| Jungleboek | 6497 | 1992 | release | The Jungle Book |
| Karmma Calling | 6108 | 2024-01-26 | first_release | The Count of Monte Cristo |
| La Dueña | 6377 | 1984 | release | The Count of Monte Cristo |
| Lost in Austen | 6278 | 2008 | publication | Pride and Prejudice |
| Monte Cristo Haku | 6354 | 2018-04-19 | release | The Count of Monte Cristo |
| Montecristo | 6081 | 2023-04-14 | first_release | The Count of Monte Cristo |
| Nihon Gankutsuou | 6074 | 1979-01-10 | release | The Count of Monte Cristo |
| Scrooge Live | 6026 | 2020 | recording | A Christmas Carol |
| Tin Man | 6239 | 2007-12-02 | release | The Wonderful Wizard of Oz |

### Exception

`Daai Bo Fuk` (6048) has an exact `P144` edge but no Wikidata date and no recognised infobox date. Its edge is approved; the work stays draft so the public “0 works without a year” invariant holds.

## 10. Batch proposal triage — 2026-10-22

Stopped treating each media slice as a separate manual review. `triage_proposals` now classifies the whole pending queue in one pass and applies only fully supported edges.

```bash
.venv/bin/python manage.py triage_proposals \
  --output docs/proposal-triage-latest.json
```

- **Green** requires exact non-deprecated `P144`, `based-on`, a dated adaptation, a specific public type, at least one Wikipedia sitelink, a public editorial seed, no conflicting edge, and valid date order.
- **Amber** stays pending: missing year, unverified date, generic type, no sitelink, title collision, or duplicate pending edge.
- **Red** is excluded: bad evidence, identity conflict, self-link, unsupported target, or an existing edge.
- Missing images are warnings, not publication blockers; placeholders remain.

### Applied result

- First pass: 364 candidates triaged: **140 green, 222 amber, 2 red**; 140 proposals approved and 140 works published.
- Red cleanup: rejected the duplicate accepted `Roméo et Juliette` (6447) and the self-linked/multi-QID Hamlet record (6004).
- Added clear screen subtype mappings: television film, animated film, feature film, short film, anime film, animated/miniseries/anime TV series, TV special, one-act play, short novel.
- Second pass: 222 candidates: **65 green, 157 amber, 0 red**; 65 proposals approved, 62 works published (3 were already public).
- Green types across both passes: film 121, musical 17, television series 19, play 12, novel 12, opera 11, video-game 7, album 4, television program 1, song 1.
- Amber reason tags overlap: generic type 94, no sitelink 82, unverified date 53, no year 36.
- 222 pending records had no image warning; this did not block publication.

### Current limits

- Public non-demo works: **328**; public works without a year: **0**.
- 157 proposals remain pending; all are amber, and 36 have an undated endpoint.
- 66 original adaptations have no Commons `P18`; newly published adaptations mostly use placeholders. No licensed image is available locally for them.
- Restricted film databases are not scraped. The remaining pending-date records are mostly records with no infobox date or only restricted IDs; use the report before spending time on them.

