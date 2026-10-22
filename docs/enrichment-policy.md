# Enrichment policy and relationship map

Status: working policy, 2026-10-21. This document limits enrichment; it does not promise full Wikidata or Wikipedia coverage.

## Principle

Store broad source payloads. Publish narrow, reviewed facts.

- `SourceRecord.raw_payload` may keep the full Wikidata entity for audit.
- Promoted fields should be only what OMA uses on a page, filter, or graph edge.
- Public pages show accepted values, not the raw supplier record.
- No full Wikipedia article text, no image ingestion, no "every Wikidata claim" mirror.

This keeps the trade-off explicit: completeness stays in the local cache; quality stays in the catalog.

## Enrichment tiers

| Tier | Fields | Why |
|---|---|---|
| **0. Identity** | QID, labels, aliases, short description, instance-of/form, external IDs (IMDb, Open Library, TVmaze, Gutenberg) | Search, disambiguation, crosswalk |
| **1. Core facts** | publication/release date with precision, creator credits (author, director, composer, screenwriter), original language, country, genre, series membership | Work page facts and filters |
| **2. Graph** | based-on, follows/followed-by, part-of-series, inspired-by, influenced-by, derivative-work, edition/translation-of | Connections and adaptation graph |
| **3. Optional** | characters, narrative location, awards, main subject, filming location, box office | Later editorial features |
| **Never bulk** | full Wikipedia prose, article sections, unlicensed images, every statement, every language variant | Cost, license, noise |

Tier 3 is not a backlog promise. Add a field only when a page or query needs it.

## Images

Images are allowed, but not by bulk scraping.

- Prefer Wikimedia Commons files with explicit license and attribution. Wikidata `P18` is a candidate source, not automatic permission.
- Open Library cover IDs/URLs are useful, but each cover is not automatically cleared. Link out by default; rehost only after checking the specific image.
- Store source URL, license, attribution, retrieval date, and the exact entity/edition.
- If no licensed image: use an OMA-generated typographic placeholder. Do not scrape a poster or cover.
- Do not use IMDb or TMDB images in public OMA without a license.

## Wikidata property map

### Identity and core

| Property | Meaning | OMA use |
|---|---|---|
| P31 / P7937 | instance of / form of creative work | Work type, with conservative mapping |
| P1476 | title | Title candidate; keep language |
| labels / aliases | names | Search aliases; keep language |
| description | short description | Short neutral summary; CC0 |
| P345 | IMDb ID | Crosswalk only |
| P648 | Open Library ID | Crosswalk only |
| P2034 | Gutenberg ebook ID | Crosswalk only |
| P8600 | TVmaze show ID | Crosswalk only |
| P577 | publication date | Date with precision; do not invent a day |
| P50 / P57 / P86 / P58 | author / director / composer / screenwriter | Credits, role-specific |
| P364 | original language | Version/Work language |
| P495 | country of origin | Work fact |
| P136 | genre | Candidate term, mapped to vocabulary |
| P179 | part of series | Series membership |

### Relationships

| Property | Direction | OMA handling |
|---|---|---|
| P144 | derived work → source work | Broad `based-on` edge. Do not auto-label "faithful adaptation". |
| P4969 | source work → derivative work | Inverse of P144; use to validate, not duplicate |
| P155 | work → previous work | `follows` / sequence, not adaptation |
| P156 | work → next work | `followed-by` / sequence |
| P179 | work → series | `part-of-series` |
| P941 | work → inspiration | `inspired-by`, separate weaker edge |
| P737 | influenced by | `influenced-by`; may point to a person or work, so validate type |
| P629 | edition/translation → work | `edition-of` / `translation-of` |
| P674 | characters | Optional; do not create character records yet |

### OMA relationship vocabulary

Start with a small, stable set:

- `based-on`
- `remake-of`
- `sequel-to`
- `prequel-to`
- `spin-off-of`
- `translation-of`
- `abridgment-of`
- `modernization-of`
- `parody-of`
- `inspired-by`
- `influenced-by`
- `part-of-series`
- `shares-universe-with`
- `edition-of`

Mapping rule: **P144 → `based-on` by default.** Refine to remake/sequel/parody only with explicit evidence. Do not infer a narrower type from title similarity or genre.

## What not to ingest

- Full Wikipedia article text or long extracts.
- Wikipedia infoboxes as a parallel fact source.
- Images, posters, covers, or logos.
- Every Wikidata statement, qualifier, or language.
- Every `P144` recursively. One hop per bounded batch.
- Rights conclusions from Wikidata. Wikidata is not a rights registry.

Wikipedia sitelinks are useful as citations and link-outs. If an extract is ever needed, store it separately with page title, revision, retrieval time, and CC BY-SA attribution. Do not mix it into CC0 fields.

## Batching and limits

The existing `run_wikidata_enrichment` command supports up to 200 seeds and a configurable related-work limit (default 1,000; safety ceiling 5,000). A dry run on 2026-10-21 hit the old 300-row cap with 50 seeds:

- 50 seeds attempted
- 299 related works returned
- 300 relationships discovered
- truncated: true
- 14 network requests, about 22 seconds

The old 300 cap was a pilot safety limit, not a coverage target. It is now configurable. A cap is still useful: it keeps one run bounded and reviewable.

A 10-seed short run with a 1,000 cap returned:

- 10 seeds attempted
- 259 related works
- 260 relationships discovered
- truncated: false
- 13 network requests, about 14 seconds

So 10 seeds fit under 1,000. A 50-seed run does not necessarily fit; it hit 300 under the old cap.

For real work:

1. Use 10–20 seeds per run, or paginate.
2. Cache every entity before transforming it.
3. Exclude deprecated statements.
4. Queue ambiguous matches; never merge on title.
5. Keep the statement ID, rank, qualifiers, references, entity revision, and retrieval time.

Wikidata Query Service may rate-limit aggressively during outages. Back off, cache, and prefer `wbgetentities` batches.

## Priority score

Do not enrich all 90k TVmaze shows or all 79k Gutenberg records. Rank:

1. Golden-set works and their direct neighbors.
2. Public works missing core fields.
3. Works with many incoming adaptation candidates.
4. Works with demand, collections, or contributor proposals.
5. Everything else: identity only.

## Public display rule

An enrichment run produces **candidates**, not public truth.

- New works: draft.
- Existing fields: fill blanks; do not overwrite editorial values.
- Relationships: `ImportRelationshipProposal`, then human approval.
- Conflicts: queue with both source IDs and evidence.
- Confidence and limitations: show them to reviewers, not as false certainty on public pages.
