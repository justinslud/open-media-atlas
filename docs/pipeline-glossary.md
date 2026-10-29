# Relationship pipeline glossary

Terms used by the staff diagnostics page, the resolver, and triage. Written to
match the code in `catalog/diagnostics.py`, `resolve_wikidata_relationships`,
and `triage_proposals`.

## The four stages

| Stage | Meaning | Where it lives |
|---|---|---|
| **Source record** | The supplier payload we cached verbatim, one row per Wikidata item. Imports never read the network again if a record exists. | `SourceRecord.raw_payload` |
| **Claim (statement)** | One assertion inside that payload, for example "this film is based on that novel". It carries a statement ID such as `Q129778$2EEA7FFF-…`, a rank, and optional qualifiers and references. | payload only |
| **Proposal** | An inert catalog row that says "Wikidata asserts X". Nothing public changes. It can be pending, approved, or rejected. | `ImportRelationshipProposal` |
| **Accepted relationship (edge)** | A proposal an editor approved. Only accepted edges appear on public work pages. | `WorkRelationship` |

**Supported claim** — a claim whose property OMA understands: P144 based-on,
P155 follows, P156 followed-by, P179 part-of-series, P629 edition-of,
P941 inspired-by, P737 influenced-by, P4969 derivative-work. Everything else in
the payload is kept but ignored by the pipeline.

## Identity terms

- **Staged work** — a catalog row created or matched for a Wikidata item. New
  ones start as `draft`, so they are invisible in public views until published.
- **Endpoint** — either work in a relationship: the derived work and the source
  work. Direction matters: `from_work` is the derived side.
- **Duplicate Wikidata identity** — one catalog work carrying two Wikidata IDs,
  usually because two related items (a film and its re-edit) were matched to the
  same row. It produces fake **self-links** and blocks otherwise correct edges.

## Visibility terms

| Term | Meaning |
|---|---|
| `visibility=public` / `draft` | Public works have a live page; drafts do not. |
| `depth=editorial` | Hand-curated seeds (the Golden 20 and similar). |
| `depth=index` | Normal browsable catalog works. |
| `depth=ambient` | Reachable by URL, list, or random only; excluded from browse and search. The long tail. |

**Accepted graph** — the set of works joined by at least one accepted
relationship. It is *not* the same as "everything public": 7,029 works are
public, 2,730 are in the graph. A public work can sit outside the graph because
nobody accepted an edge for it yet.

## Page states

| State | Meaning | Is it a defect? |
|---|---|---|
| **In the accepted graph** | At least one accepted edge names the work. | No — finished. |
| **Proposal pending review** | Claims became proposals; none accepted yet. | No — waiting on triage. |
| **Proposals exist, none accepted** | Proposals were made but none was accepted (rejected, or approved without an edge). | Sometimes — check the rejection reason. |
| **Claims exist, never resolved** | The payload has a supported claim; no proposal references it. Usually the work was never used as a resolver seed. | No — untapped, not broken. |
| **No supported relationship claim** | The payload has nothing usable, so there is nothing to resolve. | No — genuinely alone. |

## Claim outcomes (per statement)

| Outcome | Meaning |
|---|---|
| `accepted` | Proposal approved; the edge exists. |
| `proposal_pending` | Proposal waiting for review. |
| `proposal_approved` | Approved but no edge row — should be repaired. |
| `proposal_rejected` | Review rejected it; the reason is in the triage report. |
| `target_missing` | The claim points at a Wikidata item never staged as a work. |
| `no_proposal` | Both ends exist, but no proposal references this statement. |
| `self_link` | The claim points at the work's own other Wikidata ID (duplicate identity). |

## Triage colours

| Colour | Rule | Action |
|---|---|---|
| **green** | Exact property, dated derived work, specific public type, sitelink, seed in scope, no conflicting edge, date order sane. | Safe to approve. |
| **amber** | Something needs judgement: missing year, unverified date, generic type, no sitelink, title collision, duplicate pending edge. | Review by group. |
| **red** | Blocked: bad evidence, identity conflict, self-link, unsupported target, existing edge, impossible date order. | Park or reject. |

## Vocabulary and date caveats

- **`generic_type`** — the work type is a placeholder (`literary work`,
  `written work`, `creative work`), not a real form. Triage will not publish
  these without a specific type such as `novel`, `play`, or `film`.
- **`year_inversion`** — both endpoints have years and the *derived* work is
  dated **earlier** than its source. Applies only to derivation and influence
  codes, never to `follows`, `followed-by`, or `part-of-series`.
- **`calendar model`** — part of Wikidata's date value
  (`http://www.wikidata.org/entity/Q1985727`). OMA stores it only inside the
  verbatim provenance of a date claim; it is never displayed or used.
