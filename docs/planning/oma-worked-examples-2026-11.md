# OMA worked examples — 2026-11

Three real catalog records walked end to end: discovery → inspection → API retrieval →
agent contribution → correction → update propagation. The purpose is not to demo a finished
product. It is to expose where the model and workflows break, using records that already
exist in `db.sqlite3`.

Snapshot 2026-11-04 21:33 UTC. Counts drift; IDs are stable. All queries are read-only.
`VERIFIED` = read from the live catalog or rendered page. `PROPOSED` = design, not
implemented. API shapes follow
[agent-contribution-and-api-2026-11.md](agent-contribution-and-api-2026-11.md) §4 and are
**not built**.

---

## Example A — *Les Trois Mousquetaires* (work 6523): the adaptation hub

### A.1 Discovery

`/discover/?q=mousquetaires` returns 35 works in 3.7 s (83 SQL queries). The novel is
present as `novel`, 1844, editorial depth, with a Wikidata identifier `Q140527` and **two**
Open Library work IDs (`OL15561436W`, `OL36861W`) — a genuine merge candidate, not a
collision (knowledge model §6.1).

The obvious next click is "show me adaptations". `/discover/?relationship=has_adaptations`
returns **0 results** (VERIFIED), because the filter tests
`relationship_type.category == "derivation"` and the adapter's 176 edges are categorised
`reference` (`views.py:135-142`).

So the discovery journey fails at the first step for the single most-adapted work in the
catalog.

### A.2 Inspection

The work page renders (VERIFIED):

- **93 connected works · 176 accepted relationships**, all filed under **"Other direct
  connections"**; the "Adaptations" group is absent entirely. Precisely: 176 incoming rows
  = 91 `based-on` (91 distinct targets) + 84 `derivative-work` (the same 84 targets, all
  duplicated) + 1 `follows`; plus 2 outgoing (`part-of-series`, `followed-by`). So 92
  distinct incoming claims and 93 public related works.
- The connection timeline has **85 dated events**, 1845–2023, with the label "Based On" or
  "Derivative Work" on every row.
- Each related work shows *two* relationship labels for one relation: e.g. "3 Musketeers
  (2011) — Based On — Derivative Work".
- **0 versions, 0 releases.** There is no edition of the novel, no translation, no
  publication history — for a work with 93 afterlives.

The 176 rows encode 92 distinct claims: 84 `derivative-work` rows duplicate a `based-on`
row because Wikidata carries both `P144` and `P4969` for the same pair. Of the 93 public
related works, **91 are adaptation targets**, one is a sequel (*Vingt ans après*) and one is a
series container (the *trilogie des mousquetaires*). The reader sees 176 "relationships"; the
honest number is one claim per pair, with two source statements — and the 93 are three
different kinds of connection, not 93 adaptations.

**A further defect the verification path exposes:** for every property except `P144`, the
resolver stored `evidence.entity_id`/`source_url` as the *target* while the `statement_id`
belongs to the *seed*. ~2,625 edges (≈53%) therefore link to a Wikidata page that does not
contain the cited statement. On this record, most "supporting statement" links open the
adaptation's page, not the statement's.

This is the inversion the strategy proposes to fix (P0): the graph is not sparse here, it is
*doubled*, and the product's own category vocabulary hides it.

### A.3 API retrieval — PROPOSED

```
GET /api/v0/works/6523
```

```json
{
  "id": 6523,
  "canonical_url": "https://…/works/6523/les-trois-mousquetaires/",
  "title": "Les Trois Mousquetaires",
  "type": {"code": "novel", "label": "Novel"},
  "dates": [{"text": "1844", "year": 1844, "meaning": "publication",
             "precision": "year", "source": "wikidata:Q140527"}],
  "identifiers": [
    {"scheme": "wikidata", "value": "Q140527"},
    {"scheme": "ol_work", "value": "OL15561436W"},
    {"scheme": "ol_work", "value": "OL36861W"}
  ],
  "warnings": [{"code": "MULTIPLE_IDENTIFIERS_SAME_SCHEME",
                "scheme": "ol_work", "count": 2}],
  "credits": [{"agent": {"id": 1189, "name": "Alexandre Dumas"},
               "role": "author", "source": "wikidata:P50"}],
  "versions": [],
  "counts": {"relationships": 93, "claims": 92, "accepted": 176}
}
```

```
GET /api/v0/works/6523/relationships
```

```json
{
  "id": 6523,
  "cursor": null,
  "count": 93,
  "note": "93 related works = 91 adaptation targets + 1 sequel + 1 series container",
  "items": [{
    "work": {"id": 6809, "title": "3 Musketeers", "type": "film", "year": 2011},
    "direction": "incoming",
    "family": "adaptation",
    "label": "Adapted from",
    "claims": [
      {"predicate": "based-on", "statement": "Q140527$…", "rank": "normal",
       "property": "P144", "source": "wikidata", "retrieved_at": "2026-10-22T…"},
      {"predicate": "derivative-work", "statement": "Q156…$…", "property": "P4969",
       "source": "wikidata", "retrieved_at": "2026-10-22T…"}
    ],
    "review_status": "accepted"
  }]
}
```

What this exposes: the API can only be honest if `family` and `claims[]` exist. Without
them it would either return 176 items (inflating the count) or 93 (hiding that two
statements support some edges). The `warnings` array is the machine-readable form of "two
Open Library IDs on one work" — a real condition the page currently shows as two links with
no explanation.

### A.4 Agent contribution

A plausible agent task: *resolve the two Open Library IDs into one canonical work plus one
merged edition record.* Under the proposed protocol:

```
POST /api/v0/submissions
{
  "contract_version": "oma-contract/2026-11-1",
  "batch_id": "b-6523-01",
  "submissions": [{
    "client_ref": "s1",
    "idempotency_key": "sha256:…",
    "operation": "propose_identity_merge",
    "subject": {"work_id": 6523},
    "target": {"scheme": "ol_work", "value": "OL36861W"},
    "proposed": {"canonical_scheme": "ol_work", "canonical_value": "OL15561436W",
                 "basis": "same Wikidata Q140527, same title, same author"},
    "evidence": {"source_url": "https://openlibrary.org/works/OL36861W",
                 "retrieved_at": "2026-11-04T20:00:00Z", "method": "page_read"},
    "method": "model_extraction",
    "confidence": 0.81
  }]
}
```

**It fails today, and the failure is instructive.** `WorkRedirect` is the merge mechanism,
it has zero rows, and *no* proposal kind exists for identity or merge: `ContributionProposal`
allows corrections to title, description, date text, type, and three relationship fields
(`models.py:735`). The agent's only route is a free-text correction on one work — which
cannot express "these two identities are one work", cannot carry the second identifier, and
would be reviewed by a human reading prose.

**Weakness exposed:** the most valuable agent contribution in the current catalog
(identity resolution, 3,676 Wikidata-only / 5,490 OL-only works) has no schema, no proposal
kind and no review UI. The contribution protocol must not ship without an identity operation,
or agents will be restricted to exactly the low-value tail.

### A.5 Correction and propagation

Suppose a member notices the 2011 film is a modern adaptation and proposes changing the
edge type. Today:

1. Member opens `/works/6523/suggest-correction/?relationship=…`, chooses
   `relationship_type`, enters a code, an explanation, a source URL.
2. `ContributionProposal` stores `value_at_submission` (the old type code) and
   `work_updated_at`; `has_conflict` detects a changed work since submission.
3. A reviewer approves or rejects in admin. There is **no rejection reason field** on
   `ImportRelationshipProposal` and rejection prose is not shown to the submitter; on
   `ContributionProposal` there *is* `reviewer_explanation`, so the two review paths differ.
4. On approval, the work's `updated_at` changes, the relationship row's evidence history is
   appended, and `LibraryEvent` records the correction for followers.

**What is missing:** the correction changes *one* of the two duplicate rows, leaving the
pair inconsistent (one `adapted-from`, one `based-on`). The model cannot say "this pair is
one claim" — so correction cannot fix duplication; only a vocabulary/data migration can.

**Propagation to the API:** the proposed `changes?since=` feed would emit
`{"entity": "relationship", "id": 421, "op": "updated", "fields": ["relationship_type"]}` and
a snapshot diff would show the work's relationship list change. Without a claim family, the
feed consumer sees 176 relationship events where a human would see 93 changed works.

---

## Example B — *Alice's Adventures in Wonderland* (work 6012): editions that do not exist, dates that do

### B.1 Discovery and inspection

`/discover/?q=alice` returns 51 works. Work 6012 is `novel`, 1865, editorial depth, with
`Q92640` and `OL138052W`.

The page (VERIFIED) says **SOURCE PUBLICATION DATE: 1865**, and the timeline shows 54 dated
connections, 1871–2025, opening with *Through the Looking-Glass* (1871) as **Follows**.

The stored evidence is richer than the page:

```json
{"assertions": [
   {"property": "P571", "kind": "inception",  "text": "1862", "precision": "year"},
   {"property": "P577", "kind": "publication","text": "1865", "precision": "year"}],
 "disagreements": {"distinct_years": [1862, 1865]}
}
```

This is the well-known case: the story was told in 1862, published in 1865. The two values
are *different kinds of date*, not a contradiction — and the page shows only one, with no
indication that a second, differently-meaning assertion exists. `disagreements` is present
on 200 works and **read by no code and no template**.

**Versions and releases: zero** (VERIFIED). The work has an Open Library ID but no editions
were imported, so the page cannot answer "which edition", "which translation", or "is this
the 1865 first edition or a later reprint".

### B.2 The only modelled translation in the catalog is demo data

Work 1001 (*The Glass Orchard*, fictional fixture) has two versions — `original` English and
`Marchand translation` French — and three releases across them. It is the **only** work in
13,878 with more than one version, and the only `translation` version in 7,643. The model
supports the concept; the catalog does not exercise it.

Consequence: the "multiple editions or translations" journey is not currently
demonstrable on a real work. Any launch copy that promises it is false.

### B.3 API retrieval — PROPOSED, and empty

```
GET /api/v0/works/6012/versions
{"id": 6012, "items": [], "note": "no versions recorded"}
```

An empty array is honest. The failure would be to return a synthetic "Original work" version
(the importer creates one for most works: 5,500 of 7,643 are `kind="unresolved"`, labelled
"Original work"), which teaches a client that a work *has* an edition when it does not.

**Design rule this example forces:** a placeholder version is not a version. Either omit
generated placeholders from the API or mark them `synthetic: true`, and never let them count
towards "editions available".

### B.4 Agent contribution

The high-value contribution here is **edition extraction**: from the cached Open Library
payload, attach the 1865 first edition and the 1869 French translation as releases/versions.
The proposal would be:

```
operation: "add_release"
subject: {"work_id": 6012}
target: {"version": {"kind": "translation", "language": "fr"}}
proposed: {"title": "Aventures d'Alice au pays des merveilles",
           "publication_date_text": "1869", "publisher": "Macmillan"}
```

**It cannot be expressed.** `ContributionProposal` has no version/release operation, no
language field, and `suggest_correction` cannot create child records. An agent could only
write a free-text correction to the work's description.

**Weakness exposed:** the single most valuable data type for the product (editions and
translations) has no contribution path at all. Before building an agent API, the proposal
model needs at least `add_version`, `add_release`, `add_credit`, `add_identifier` — otherwise
"agents as primary contributors" means "agents may fix typos".

### B.5 Correction and propagation

A member today can propose a change to `first_publication_date_text` only. They cannot:

- record a *second* date with a different meaning (1862 inception);
- mark 1865 as "first edition, first issue" vs a later reprint;
- attach the edition that would make the claim checkable.

Approval writes one date and `date_evidence` with a source URL; the previous value is kept
in `FieldEvidence` history. Propagation works for the work field, but the edition/translation
journey remains impossible until the model and contribution path change (P1, P3 in the
strategy).

---

## Example C — *Alice in Pornoland* (work 6121): conflicting sources and a doubled edge

### C.1 Discovery and inspection

A reader searching "Alice" finds a 1993 Italian film among 51 results. It is `film`, public,
index depth, with `Q12835640` and an internal IMDb crosswalk `tt0128035` (never displayed).

The page says **SOURCE RELEASE DATE: 1993** and lists **1 connected work · 2 accepted
relationships** — the duplicate pair again, this time between a film and its source novel
(*Alice's Adventures in Wonderland*, 6012). The "Why this value?" panel discloses a
**title** alternative (`Alice nel paese delle pornomeraviglie`) but says nothing about the
date.

The stored evidence has three `P577` assertions (VERIFIED):

```json
{"same_property_conflicts": [{"property": "P577", "values": [
   {"text": "1993",          "precision": "year"},
   {"text": "1993-11-01",    "precision": "day"},
   {"text": "1998",          "precision": "year"}]}]}
```

Three claims, one displayed, zero disclosed. The selection rule ("publication preferred over
inception, then preferred rank, then earliest assertion") is documented in `dates.py`, but
not visible to the reader, and "1998" may well be a different release territory or a
re-release.

### C.2 What this record is good for

It is evidence that the catalog's declared domain already includes adult derivative works
without special handling. The record is factual, has no explicit content, and is a real
adaptation. That is the correct default: OMA catalogs works, not taste. But it forces a
policy decision the plan does not yet make: **does a work that is itself an adaptation of a
canonical work inherit any content policy?** Proposed default: no content gating on factual
records; a separate, explicit policy only if a surface (images, excerpts) would carry
explicit material. Record this rather than discover it during launch review.

### C.3 API retrieval — PROPOSED

```
GET /api/v0/works/6121
```

```json
{
  "id": 6121, "title": "Alice in Pornoland", "type": "film",
  "dates": [{"text": "1993", "year": 1993, "meaning": "release",
             "precision": "year", "selected": true,
             "alternatives": [
               {"text": "1993-11-01", "precision": "day", "statement": "Q…$1"},
               {"text": "1998", "precision": "year", "statement": "Q…$2"}],
             "disagreement": "same_property"}],
  "relationships": {"count": 2, "claims": 1,
                    "warning": "DUPLICATE_PREDICATE_FAMILY"}
}
```

This is the shape that makes uncertainty usable by software. Today no endpoint exists and
the page hides both facts.

### C.4 Agent contribution

The useful agent proposal is not "change the date" but **"record a competing claim with
scope"**: 1998 is likely a re-release or a different territory. The submission would carry
`operation: "add_claim"`, `predicate: "release_date"`, `value: "1998"`,
`qualifiers: {"territory": "IT"}`, `contradicts: []`. Under the current model the agent
cannot: there is no `Assertion` table, and `suggest_correction` would *replace* the value,
destroying the competing claim rather than adding to it.

**Weakness exposed:** the proposal vocabulary is "replace a field", which is the wrong
primitive for a reference. The correct primitive is "add a claim", with review deciding what
the page foregrounds.

### C.5 Correction and propagation

A member who believes 1993-11-01 is the correct first release:

1. Proposes `first_publication_date_text = "1993-11-01"`, with a source URL.
2. `has_conflict` compares `work.updated_at` — no other change, so it applies.
3. Approval sets the field, writes `date_evidence`, archives the old value in
   `FieldEvidence`, and the page updates.

The *other two* claims survive only inside the JSON blob, unread. There is no way for the
next reader to see that this was contested, and no way for the next agent to know a
correction already happened without reading `FieldEvidence`.

**Propagation check:** the API's `history` resource must expose the field evidence chain, or
every correction is invisible to machines even when it is visible to people.

---

## Cross-cutting findings

| Finding | Evidence | Consequence |
| --- | --- | --- |
| The central adaptation journey is broken by vocabulary and code, not data | 0 results for `has_adaptations`; a corrected family filter reaches ~430 works (not >1,000); 93 works all in "Other direct connections" | P0 is right, but code-only (no migration) |
| Verification is broken for half the graph | ~53% of evidence links open an entity that does not hold the cited statement | Fix before any "Adapted from" label or conflict disclosure |
| Duplicate claims inflate every count | 752 pairs; 176 rows → 92 claims on 6523; 2 relationships on 1 pair for 6121 | Fix `claim_family` before any coverage metric |
| Editions/translations are absent where they matter most | 0 versions on 6012 and 6523; 1 translation in the catalog, demo | Do not promise edition comparison at launch; P1 should target editions for the canon |
| Competing claims are stored but invisible | 200 works with `assertions`/`disagreements`; no reader, no API | P2 disclosure; `add_claim` primitive |
| Contribution cannot express the valuable operations | No identity, edition, credit or claim operations in `ContributionProposal` | Agent API without these is a typo service |
| Review is the bottleneck | 0 proposals ever, 1 staff, 1,062 pending, 0 reviewed evidence | Agent pilot must be measured on reviewer minutes |

## What these examples change in the plan

1. **P0 stays first.** The vocabulary fix is what makes examples A and C readable.
2. **P1 is re-scoped** from "creator pages" to "creator pages **and** editions for the
   canon" — otherwise the second promise of the product is undemonstrable.
3. **The agent protocol must ship with `add_claim` and identity operations**, or it is not
   worth building (DR-02 consequence).
4. **A placeholder version is not a version.** Exclude synthetic placeholders from API and
   public counts, or the catalog claims an edition layer it does not have.
5. **Content policy is a real decision**, prompted by 6121: factual records of adult works
   are in scope; explicit media are not.
