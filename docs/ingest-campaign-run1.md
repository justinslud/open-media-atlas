# Ingestion campaign, run 1 — scoped milestone

Approved 2026-11-04 by the project owner. This document is the scoped milestone that
`AGENTS.md` requires before bulk ingestion. It authorizes one bounded, long-running
campaign; it does not authorize hosting, publishing, or any source not listed here.

## What "filled out" means

Not catalog size. The target is that sources meet each other:

- a work discovered in one source acquires its identity in the others that have it;
- when two records describe the same work, an edge or an identity link exists;
- the graph grows from those joins, not from more orphan rows.

Works that stay unconnected are acceptable. Books nobody catalogued elsewhere have no
partner source to link to, and inventing one would be worse than leaving them alone.

## Baseline measured 2026-11-04

| Measure | Value |
| --- | --- |
| Works / public / draft | 13,878 / 7,452 / 6,426 |
| Accepted relationships | 3,779 |
| Works carrying a Wikidata ID | 8,375 |
| Works carrying an Open Library ID | 10,198 |
| Carrying both (crosswalked) | **4,699** |
| Wikidata-only / Open Library-only | 3,676 / 5,499 |
| Public Wikidata works without an edge | 3,742 |
| Public Open Library works with an edge | 566 |
| Public works with no edge at all | 4,237 (4,092 of them books) |
| Pending relationship proposals | 1,062 |

Steering metrics, in order: crosswalked works; public works with an edge; accepted
edges per source; precision against the truth set. Catalog size is not a metric.

## Direction

Wikidata is the seed and the spine. Open Library, Project Gutenberg and TVmaze attach
to it. The earlier inverted route — import from Open Library and hope to connect
outward — is what produced 4,092 edge-less public books. Do not repeat it.

IMDb is an internal identity crosswalk only: matching and disambiguation. Its records
are never displayed publicly, never redistributed, and never copied into fixtures or
exports.

Music (MusicBrainz, Discogs) is out of scope for this run, as are new node types:
creators and series become first-class graph nodes in a later run, not this one.

## Cycle

1. Select seeds — Wikidata-only works, then thin regions of the existing graph.
2. Crosswalk — attach identities from the allowlisted sources to each seed.
3. Mine edges — exact identifiers and claims only, never title-only inference.
4. Triage — green means an exact identifier plus an allowlisted relation type.
   Green is accepted automatically; everything else is queued for a human.
5. Measure — yield per source, per strategy, scored against the truth set.
6. Record what was tried, what won, and what to try next.

## Standing rules

- Green-only auto-acceptance. No bulk approval of amber or red, no self-link edges,
  no relationship inferred from a shared title.
- Never modify `visibility`, publication depth, or rights statements as part of
  ingestion. Enrichment does not publish.
- Any write to the original local catalog: fresh SQLite backup-API snapshot, reopen
  and integrity check, manifest, schema/identity fingerprint recheck, then a
  transactional additive/idempotent apply. Preserve competing facts.
- Source provenance is recorded per claim. Disagreements are retained, not resolved
  by preference.
- Code changes are prepared in the campaign's isolated workspace with a diff and
  passing checks. Opening a pull request against `justinslud/open-media-atlas` is a
  separate, human-approved step; the campaign never pushes, merges or deploys.
- No source is adopted because a dataset was convenient. A new source enters the
  allowlist only by an explicit human decision, with its terms recorded here.
- Network imports never run during a web request, build, migration, or startup, and
  every import keeps an explicit bound and a recorded run.

## Truth set

Sixty blind items, judged once by the project owner in about ten minutes from the
factory dashboard: twenty crosswalk pairs, twenty edge claims, twenty traps that must
be rejected. The judged
sample becomes the precision gate. A strategy that improves coverage while losing
precision against that gate is reverted, not celebrated.

## Sources in scope

| Source | Role | Terms note |
| --- | --- | --- |
| Wikidata | seed, identity, claims | CC0 |
| Open Library | identity, editions | local pinned dumps |
| Project Gutenberg | ebook identity | supplied rights statements kept separate |
| TVmaze | television identity | CC BY-SA, attribution retained |
| IMDb | internal crosswalk only | non-commercial terms, never displayed |

A TV/film dataset beyond these may be researched. Adoption needs the owner's explicit
yes and a line in this table.

## Stopping

Stop and report when: two consecutive slices add no accepted edge; a backup or
integrity check fails; quota is limited; or the truth-set precision gate regresses
twice. Otherwise continue, checkpointing caveman-short facts with one decision.
