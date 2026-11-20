# Agent contribution and a reader API for Open Media Atlas

Draft · 4 November 2026 · **PROPOSED design, no implementation.**
Every statement is either **OBSERVED** (cited `path:line`, or a SQL definition for a count) or **PROPOSED**. Endpoints, fields, codes, and quotas that do not exist in code are PROPOSED. Nothing was executed against the app: no writes, migrations, imports, mutating tests, network fetch, or commit.

Three counts in the brief differ from my measurements, so I state both. `WorkRelationship` rows: **4,504**, all `review_status='accepted'` (0 `unreviewed`, 0 `disputed`); **4,144** have both endpoints public. The brief's 4,197 is near my 4,180 with a public *source* endpoint; I use 4,504 and 4,144. Public works: 7,452 including 3 `is_demo`; `public_works()` drops demo rows once real records exist (`catalog/views.py:47-54`), leaving 7,449 reachable and **6,242 browsable** (public, not `depth="ambient"`).

This is also out of milestone scope as written. `AGENTS.md` forbids new infrastructure and AI enrichment without a scoped milestone; the page map defers write APIs and agent credentials (`docs/planning/OpenMediaAtlas-Page-and-Action-Map-v0.1.md:148`). §8 proposes the gate.

---

## Editor's note (lead, 2026-11-04, after independent critique)

This document was written before the independent critique of the plan. Three of its figures
are corrected here and in the decision register; the design argument is otherwise unaffected:

- "~35 reviewer-days" is **~35 reviewer-hours** (1,062 × ~2 min ≈ 35.4 h ≈ 4.4 working days).
  Quota arithmetic that depends on this number should use hours.
- "All accepted edges carry no recorded reviewer" is **false**: 3,774 rows carry
  `evidence.reviewed_at` and their proposals carry `reviewer_id=1`. What is true is that
  review is not first-class/queryable provenance and no `FieldEvidence` row has
  `origin="reviewed"`.
- The "caused a production-wide 500" claim is **unverified**: `CURRENT.md:946` records a local
  SQLite expression-tree failure, not a production incident. The scan cost is real; the
  outage is not established.
- The degree distribution (42.6% isolated) was measured at 21:20; by 21:45 the campaign had
  added edges and it read 36–43% depending on the filter. Use it as a range, not a constant.

The critique's conclusion is adopted by the strategy: **do not build the agent pilot yet** —
no account in the database can authenticate, no partner exists, and the review queue is the
bottleneck.

---

## 1. The contribution surface as it exists

### 1.1 Three write channels

| Channel | Entry point | Who | Review |
|---|---|---|---|
| Browser proposals | 5 POST routes, `catalog/urls.py:12-19` | logged-in, email-verified | Django admin, `catalog.review_contributionproposal` |
| Django admin | `catalog/admin.py` (Work, WorkRelationship, ImportRelationshipProposal actions) | staff | none — the edit *is* the decision |
| Management commands | `catalog/management/commands/` | operator at a shell | none |

The third is how the data arrived: 90 ImportRuns, 14,548 `ImportItem` rows `created`, 14,075 SourceRecords. The first has carried **zero** rows.

### 1.2 One journey, four forms

Entry points are four links on a public work page (`templates/catalog/work_detail.html:21-24`), each `@login_required` (`views.py:477-479`, `526-528`, `575-577`, `673-675`). All four share one shape: GET renders `catalog/contribution_form.html` with a CSRF token (plus an HTMX target search for relationships); POST validates the form, then email verification (`views.py:473-474`, `507-510`), then rate limit (`views.py:511-512`), then creates the row and redirects to `my-contributions` (`views.py:520`, `550`, `596`, `702`). The submitter later reads an HTML page; the reviewer works in an admin change form.

**Correction** (`forms.py:36-64`): `field_name` over exactly seven values — `title`, `description`, `first_publication_date_text`, `work_type`, `scope_note`, `relationship_type`, `authorization_statement`; `proposed_value` ≤2000 chars with per-field caps 300/300/80/2000; `explanation` ≤2000; `source_url` http(s) only. The choice list narrows at request time: relationship fields only with a valid `target_relationship`, `authorization_statement` only when the stored edge already has one (`views.py:495-498`). Only **public** works are targetable: `get_object_or_404(public_works(), pk=pk)` (`views.py:483`).

**Relationship** (`forms.py:67-103`): `related_work` (RadioSelect over all public non-merged works), `relationship_type` (all 56), `explanation`, `source_url`. `clean()` rejects an edge that already exists or is pending (`forms.py:99-102`).

**Access link** (`forms.py:134-170`): ModelForm over `AccessLink` (`provider`, `url`, `category`, `version`, `release`, `scope_note`, `language`, `region`, `restrictions`, `last_checked`) plus `action` (`replace`/`remove`), `explanation`, `source_url`; the POST body is serialised into `proposed_value` as a JSON snapshot of exactly `LINK_FIELDS` (`access.py:9-17`, `forms.py:164-170`).

**Term** (`forms.py:106-131`): `term`, `provenance_note`, `source_url`. Unusable today: `catalog_term` has **0 rows**, so the choice list is empty.

### 1.3 The state machine that already exists

`ContributionProposal` has five states (`models.py:661-666`):

```
pending ──approve────────────▶ approved
   ├────reject (explanation required)──▶ rejected
   └────request_clarification (explanation required)──▶ clarification_needed
                                              │ resubmit (owner only)
                                              ▼ replacement row, pending,
                                                supersedes → old = superseded
```

- Approval needs `catalog.review_contributionproposal` (`models.py:776`); rejection and clarification each require non-empty text (`models.py:784-785`, `875-876`).
- Approval refuses a stale target: `has_conflict` compares `current_value` to `value_at_submission` for corrections and access links, and `updated_at` snapshots plus edge existence for relationships (`models.py:729-735`, `786-787`); the reviewer must tick `reconcile_conflict`. This is a real compare-and-swap, but computed only at review time.
- `resubmit` is owner-only, allowed only from `clarification_needed`, and creates a new immutable attempt linked by `supersedes` (`models.py:888-921`); the correction form disables `field_name` so a revision cannot become a proposal about a different field (`views.py:647-650`).
- `ContributionRevision` is `OneToOne` and written **only on approval** (`models.py:864-868`, `927-944`). Rejected and superseded rows have no revision; their history is the proposal itself.
- Terms use a parallel, weaker machine: `pending/accepted/rejected`, a partial unique on `(work, term)` (`models.py:475-484`), and a `Source` created on acceptance (`models.py:486-509`).
- Relationship review has **no rejected state**: only `accepted|unreviewed|disputed` (`models.py:532`). Rejection means delete or leave unreviewed.

### 1.4 Five validation layers

1. Form: character caps, URL scheme, vocabulary-code existence (`forms.py:44-64`).
2. `Model.clean()`: field allowlist, "relationship must belong to this work", "a correction cannot include a relationship", self-edge ban (`models.py:737-773`).
3. Database: `unique_work_relationship`, `relationship_not_self`, `unique_active_work_term_assignment`, `unique_work_scheme_value` (`models.py:537-540`, `479-484`, `654`).
4. Approval-time: `full_clean()` plus the conflict gate (`models.py:790-793`).
5. Approval side effects, field-specific: a date correction re-parses the year and overwrites `date_kind`/`date_evidence` (`models.py:830-837`); a title correction re-slugs the work (`838-840`); a relationship-type correction rewrites evidence and creates a `Source` (`816-822`); an access approval re-runs `proposed_link()` and stamps `reviewed_at` (`796-802`).

### 1.5 Where it breaks for a machine

1. **HTML only.** No route returns JSON for a proposal. The single `Accept: application/json` branch in the app is the library save/follow toggle (`library_views.py:51-52`).
2. **No receipt.** The response is a redirect; the client never learns the new ID except by parsing a page listing all its proposals.
3. **No idempotency.** A retried POST creates a second proposal; the only guards are relationship-level (`forms.py:99-102`) and the term partial unique.
4. **Prose errors.** Field errors render as HTML (`{{ field.errors }}`); the rate-limit path is an HTML 429 (`views.py:512`). Nothing carries a code to branch on.
5. **Browser auth.** Session cookie plus scraped CSRF token; no token class exists — `accounts/models.py` contains only `EmailVerification` and `AuthRateLimit`.
6. **Verification has no machine path.** `views.py:473-474` gates submission on `EmailVerification.verified_at`, which requires an SMTP link (`accounts/services.py:19-26`). This database has **0 verified rows** and **1 user** (`admin`, superuser), so no account here can submit at all.
7. **Outcomes are undiscoverable.** No notification, webhook, or status endpoint; `review()` sends no mail (only account flows do). Polling HTML is the only option.
8. **Rejection is unlearnable.** `reviewer_explanation` is free text (`models.py:684`); three rejections teach an agent nothing general.
9. **Targets are browser controls.** Relationship targets require the HTMX radio list (`views.py:557-572`); there is no lookup-by-identifier path.
10. **Most of the catalog is unreachable.** Corrections are limited to `public_works()`, so the 6,426 draft rows — where incomplete data lives, including 4 deliberately draft undated books per `CURRENT.md` — cannot receive corrections. "Add a missing work" is in the page map (`Page-and-Action-Map:108`) but has **no route and no model**: none of the 31 paths create a Work, Agent, Version, Release, Credit, or ExternalIdentifier.

For a person it is thin too: the promised review queue page (`Page-and-Action-Map:121`) does not exist, review is one admin form at a time (`admin.py:633-677`), conflicts are an ungrouped boolean column (`admin.py:657-658`), and contributors never see each other's submissions.

### 1.6 What the data says

| Measure | Value |
|---|---|
| `ContributionProposal` / `ContributionRevision` | **0 / 0** |
| Verified accounts / users / staff | **0 / 1 / 1** |
| `FieldEvidence.origin` | 41,740 `imported`, 609 `unrecorded`, **0 `reviewed`** |
| Pending `ImportRelationshipProposal` | **1,062** of 4,849 |
| `WorkRedirect` rows | **0** (merge path never exercised here) |
| `AccessLink` | 32, all `active`, **0 with `reviewed_at`** |
| Degree, browsable public works | 0 edges: **2,661** (42.6%); 1: 2,185; ≥5: **228** (3.7%) |

The proposal pipeline has never carried an item in production. And `work_provenance()` can render "Human-reviewed" (`provenance.py:83`), but **no row in this database can produce that state** — `origin="reviewed"` is written only by reviewed corrections (`models.py:844-847`). The review vocabulary is aspirational, which matters before agents are pointed at it.

---

## 2. Agent-first contribution (PROPOSED)

### 2.1 Principles

The reviewer is the scarce resource — not the submitter, not the CPU. One authorization path for browser, admin, command, and API (`Permissions-Matrix:58`). Attestation, not volume. The contract is generated from the validator, or it will drift (`publication.py:3-5` states exactly this principle for triage rules). No silent auto-accept in v0 (§3.4).

### 2.2 Discovery: gap queues

`GET /api/v0/queues` → ids `missing_creator` (637 at the last audit), `missing_date` (115), `generic_type` (350), `relationship_pending` (1,062), `access_unverified` (32), `provenance_missing`. Items: `{work_id, href, gap_code, blocking, suggested_operation, contract_hint}`.

Do not build this naively. `publication_warnings()` calls `work.credits.exists()` per work (`publication.py:47`), so an unbounded queue is 6,242 queries. PROPOSED: a materialised `work_gap(work_id, code, computed_at)` table refreshed by a management command — or, if no table is authorised, a bounded sample that says `"sample": true` in the body.

### 2.3 Learning the schema without reading our source

- `GET /.well-known/oma.json` — api base, major version, contract version, docs, review policy, rate policy, contact.
- `GET /api/v0/openapi.json` — OpenAPI 3.1, paths and envelopes.
- `GET /api/v0/contract` — the semantics OpenAPI cannot express, with `generated_from` so drift is detectable:

```json
{"contract_version": "oma-contract/2026-11-1",
 "generated_from": "catalog/models.py:ContributionProposal.clean",
 "operations": {
   "correct_field": {"subject": {"type": "work", "must_be": ["public"]},
     "fields": {"title": {"type": "string", "max_length": 300},
                "first_publication_date_text": {"max_length": 80,
                  "side_effects": ["reparse_year", "set_date_kind"]},
                "work_type": {"type": "vocabulary", "vocabulary": "work-types"},
                "scope_note": {"max_length": 300, "requires": "relationship_target"},
                "authorization_statement": {"requires": "existing_attributed_statement"}},
     "required_evidence": ["source_url"], "review": "human"},
   "assert_relationship": {"target": "public_work", "vocabulary": "relationship-types",
     "required_evidence": ["source_url", "explanation"], "review": "human",
     "rejected_if": ["edge_exists", "duplicate_pending"]}},
 "vocabularies": {"work-types": {"count": 15}, "relationship-types": {"count": 56}},
 "limits": {"max_batch_items": 100}}
```

The field list, caps, and `requires` rules are exactly what `models.py:752-773` and `forms.py:47` enforce; a hand-written contract disagrees with the validator within one release.

- `GET /api/v0/vocabularies/{name}` — every code with `label`, `inverse_label`, `category`, `active`. The 15 work types and 56 relationship types are already code-bearing (`models.py:11-17`, `515-522`); exposing them removes most `VOCABULARY_CODE_UNKNOWN` round-trips.
- `GET /api/v0/errors` — code registry with `since` and `deprecated_at`.
- `GET /api/v0/examples/{operation}?outcome=accepted|rejected|conflict` — full request/response pairs, including a rejection with codes and a conflict with the rival submission.

Every response echoes `contract_version` / `X-OMA-Contract`; an unsupported version fails before validation with the supported list.

### 2.4 The envelope

`POST /api/v0/submissions`, batch-first, per-item results:

```json
{"contract_version": "oma-contract/2026-11-1", "batch_id": "6f1c…",
 "principal": {"operator_id": "op_8812", "run_id": "run_77", "session": "…"},
 "submissions": [{"client_ref": "s1", "idempotency_key": "sha256:…",
   "operation": "correct_field",
   "subject": {"work_id": 1234, "expected_updated_at": "2026-10-30T12:00:00Z"},
   "target": {"field": "first_publication_date_text"},
   "proposed": {"value": "1965-04-11"},
   "evidence": {"source_url": "https://example.org/item/42",
                "quoted_text": "First published April 11, 1965.",
                "retrieved_at": "2026-11-03T18:22:00Z", "method": "page_read"},
   "method": "model_extraction", "confidence": 0.72, "contradicts": []}]}
```

Response is 207 with a verdict per item, because one malformed item must not discard 99 good ones:

```json
{"batch_id": "6f1c…", "counts": {"accepted": 1, "rejected": 0, "duplicate": 0},
 "results": [{"client_ref": "s1", "state": "accepted", "submission_id": "sub_a71",
   "review": {"status": "pending", "poll_after_seconds": 60,
              "corroboration_count": 1, "conflict_group": null}, "replayed": false}]}
```

Field rationale:

- `client_ref` — stable within the batch, the only key in results; never a database id.
- `idempotency_key` — stored as `(principal_id, key) → submission_id` for 30 days. Same key and body → the original result with `"replayed": true`; same key, different body → `IDEMPOTENCY_KEY_REUSED` (409).
- `batch_id` — client-generated; replaying it returns the same `client_ref → submission_id` mapping. `atomic: true` is deliberately **not** offered: partial failure is normal, and all-or-nothing encourages full retries, which is how duplicates are born.
- `subject.expected_updated_at` — optional precondition; mismatch returns `SUBJECT_STALE` with the current value and creates no row. This is `has_conflict` moved to submission time.
- `method` — `human_entered | supplier_import | crosswalk | model_extraction | programmatic`; it selects review weight and answers "how did this fact arrive?"
- `confidence` and `contradicts` — a client-declared `[0,1]` value that grants **no** shortcut in v0 (so agents do not optimise for it), and an optional list of disputed submission ids that opens a conflict group (§2.7).

### 2.5 Stable codes

| Code | HTTP | Payload |
|---|---|---|
| `CONTRACT_VERSION_UNSUPPORTED` | 400 | `supported[]` |
| `BATCH_TOO_LARGE` | 400 | `max` |
| `AUTH_MISSING` / `AUTH_EXPIRED` | 401 | — |
| `SCOPE_INSUFFICIENT` | 403 | `required_scope` |
| `PRINCIPAL_SUSPENDED` | 403 | `reason_code` |
| `SUBJECT_NOT_FOUND` | 404 | — |
| `SUBJECT_NOT_PUBLIC` | 409 | `visibility` |
| `SUBJECT_MERGED` | 409 | `canonical_work_id` |
| `TARGET_FIELD_NOT_PROPOSABLE` | 422 | `allowed[]` |
| `VALUE_TOO_LONG` | 422 | `limit` |
| `VALUE_EMPTY` | 422 | — |
| `VOCABULARY_CODE_UNKNOWN` | 422 | `vocabulary`, `allowed_url` |
| `URL_UNSAFE` | 422 | — |
| `EVIDENCE_REQUIRED` | 422 | `field` |
| `CONFIDENCE_OUT_OF_RANGE` | 422 | — |
| `SUBJECT_STALE` | 409 | `current_value`, `current_updated_at` |
| `DUPLICATE_PENDING` | **200** | `submission_id` |
| `EDGE_EXISTS` | **200** | `relationship_id` |
| `SELF_REVIEW_FORBIDDEN` | 403 | — |
| `OPERATION_NOT_PERMITTED` | 403 | `class_required` |
| `QUOTA_EXCEEDED` | 429 | `class`, `limit`, `resets_at` |
| `RATE_LIMITED` | 429 | `retry_after_seconds` |
| `IDEMPOTENCY_KEY_REUSED` | 409 | — |

Two deliberate choices. `DUPLICATE_PENDING` and `EDGE_EXISTS` return 200 because the desired state already holds. And `EVIDENCE_UNRETRIEVABLE` does **not** exist: OMA does not fetch submitted URLs (`forms.py:42`), and an API must never imply it read a source it did not. Validation order is fixed and documented (contract → auth → schema → subject → target → value → evidence → duplicate → quota) so an agent fixing one error at a time converges.

### 2.6 States, and following a submission

Expose the five that exist plus **`withdrawn`** (PROPOSED: a submitter may withdraw while pending; today only a reviewer can move a row, `models.py:782-783`).

Two additions make the machine readable: a structured `decision_reason_code` (`evidence_insufficient`, `source_unreliable`, `does_not_match_value`, `conflict_unresolved`, `field_not_proposable`, `duplicate`, `out_of_scope`, `policy`, `other`) alongside the free-text explanation; and `review.reviewer_class: human | automated | unrecorded` with `reviewed_at`. The codebase already refuses to overstate review in prose (`provenance.py:169-171` distinguishes "Human-reviewed" from "Accepted catalog connection; human review date not recorded") — make it a field. Without a reason code, "agent-first contribution" means "agent submits and is told no in English, forever".

Follow-up: `GET /api/v0/submissions/{id}` with an `ETag`, and `GET /api/v0/submissions?batch_id=&since=&state=` where `since` is a monotonic `updated_seq`, not a timestamp, so a same-second review cannot be missed. Webhooks are PROPOSED and deferred — polling a documented endpoint avoids an outbox the project does not need.

### 2.7 Conflicts and corroboration

Three shapes; only the first exists.

1. **Staleness** (exists): `models.py:729-735`, `786-787`. Machine form: `SUBJECT_STALE` at submit, `has_conflict` at review.
2. **Disagreement** (missing): two live submissions, same `(subject, target)`, different values. PROPOSED group key `(work_id, field)` for corrections, `(from,to,type)` for edges; response carries `conflict_group` and `conflicts_with[{submission_id, value_hash, principal_class, method}]`; reviewers get a grouped view. Nothing auto-resolves — the matrix already requires a human for record changes (`Permissions-Matrix:41`).
3. **Corroboration** (missing, and the important one): identical value for the same `(subject, target)` collapses into **one review item with an attestation list**, counting **distinct operators**, not tokens. `corroboration_count` makes a triple-attested fact cheaper to review — the only mechanism here that actually reduces review cost.

The rule that must be enforced, because it is the failure mode of every agent-contribution scheme: **ten sessions reading one Wikidata item are one source, not ten.** Otherwise the galaxy manufactures consensus.

### 2.8 History

History lives in four stores with three shapes: `FieldEvidence` (a ledger, `current` flag, but only three fields — `provenance.py:8`, constrained at `models.py:968-970`); `ContributionRevision` (approval-only); `WorkRelationship.evidence` JSON (`correction_history`, `evidence_history`, `*_reviewed_at` — `models.py:551-570`, `807-821`); `WorkRedirect` (0 rows).

PROPOSED: one read projection, `GET /api/v0/works/{id}/history?field=`, rows `{at, actor_class, operation, previous_value, new_value, source_url, review_state, origin_store, submission_id?}`. Read-only; no new write path. `origin_store` must be present because the stores are not equivalent — a `FieldEvidence` row is a value association, a `ContributionRevision` is an accepted human decision, an `evidence_history` entry is a prior assertion. Collapsing them would claim more certainty than exists.

### 2.9 Quotas

Existing: `LIMITS["contribution"] = (10, 1 hour)` keyed by `HMAC(REMOTE_ADDR|user_id)` (`accounts/rate_limits.py:12-24`), no daily cap, no classes.

PROPOSED — derived from **review** capacity, because that is the binding constraint:

| Class | Items/hour | Items/day | Per batch | Batches/day |
|---|---|---|---|---|
| `read` (anonymous) | 600 req | — | — | — |
| `contributor:probationary` | 10 | **25** | 20 | 5 |
| `contributor:trusted` (≥20 accepted, <5% rejected) | 60 | **100** | 100 | 3 |
| `service:import` (named source) | 300 | 2,000 | 500 | 4 |
| `reviewer` (human) | — | 5,000 actions | — | — |

The arithmetic, since an underived number is superstition: a reviewer sustains roughly **30 decisions/hour** on the admin form (`admin.py:617-677` needs current value, proposed value, source URL, and typed text for any rejection — two minutes each is optimistic). One hour a day = 30/day. The queue already holds 1,062 pending relationship proposals = **~35 reviewer-days**. So admit no more per day than half a day's capacity (≤15/day across all principals) while the backlog exceeds 500; per-principal 25/day with a class-wide 15/day cap is the version that cannot be gamed by minting operators.

Calibration: (1) instrument the reviewer, not the agent — decisions/day and median seconds/decision, both derivable from `reviewed_at`; (2) after 30 days and ≥100 decisions, compute acceptance and duplicate rates per `(operation, method, class)`; (3) reset quotas so admitted items/day ≤ 0.5 × capacity, and cap any class below 40% acceptance at 25/day; (4) publish current numbers at `/api/v0/policy` so agents self-throttle; (5) re-calibrate quarterly, and only promote `confidence` to a *review-ordering* signal after measuring that it predicts acceptance.

### 2.10 Abuse

Probation by default (first 20 items flagged, never fast-pathed). Reputation attaches to the **operator**, so five credentials share one reputation and corroborate once. A 24h hold window for probationary batches means a garbage run costs reviewers nothing when withdrawn. Pattern checks, not content policing: per-principal value entropy on a field (40 titles across 40 works is normal; 40 titles for one work is an attack), identical `quoted_text` across many works (copy-paste hallucination), submission rate diverging from acceptance rate. No URL fetching — a cited URL is a claim, not a verification (`forms.py:42`). Kill switches at credential and operator level; approved facts stay attributed, because the matrix forbids erasing history (`Permissions-Matrix:52,107`). And rate-limit reviewer decisions: a compromised reviewer is worse than a thousand bad submissions.

### 2.11 Three kinds of change, three channels

| Class | Examples here | Channel | Decider |
|---|---|---|---|
| Contributing data | title, date, type, edge, access link, term assignment | `POST /api/v0/submissions` | reviewer, human |
| Proposing editorial change | `Term` vocabulary, display policy (`presentation.py:5-13`), seed rules (`publication.py:10-13`), connection grouping (`connections.py:20-25`) | `POST /api/v0/editorial-proposals`, **no write path to live config** | curator, human |
| Changing platform rules | review thresholds, quota classes, abuse definitions, retention, who reviews | **not an API**: human-owned RFC recorded in `docs/` | administrators, human |

An API that can both propose and approve a vocabulary term can define the categories the catalog uses. `Term` has no review model at all (`models.py:421-443`), while the matrix promises "propose new terms… not instantly public filter options" and a curator role (`Permissions-Matrix:9,43`) — unimplemented. The API must not become the shortcut around an unbuilt governance step.

### 2.12 Sessions are not contributors

`catalog.Agent` already means a **creator** (13,124 rows, `kind ∈ {person, organization}`, `models.py:228-235`). Using "agent" for AI contributors makes every future reader disambiguate from context. PROPOSED naming: **`principal`** (the automated contributor), **`operator`** (the verified human or organisation that delegated), **`Agent`** untouched.

```
operator (verified account) → principal (reputation lives here)
  → credential (scopes, expiry) → run (one session or campaign) → submission
```

A `run` is what can be paused, withdrawn, audited. A `principal` accrues reputation. An `operator` is accountable. A thousand sessions tonight is one operator, one principal, one reputation — fairer, and the only way the §2.9 arithmetic holds.

---

## 3. Authentication and permissions

### 3.1 Classes

No token exists today (`accounts/models.py`: only a one-time email hash and a rate-limit counter). PROPOSED:

| Class | Issued to | How | Scopes | Review |
|---|---|---|---|---|
| `public` | nobody | no credential | `catalog:read` | — |
| `contributor:probationary` | verified operator | self-serve | `submission:write`, `submission:read_own`, `catalog:read` | always human, lowest weight |
| `contributor:trusted` | operator with ≥20 accepted | human grant | + `vocabulary:propose` | human, higher quota |
| `service:import` | approved source owner | human grant, **source-scoped** | `submission:write` for one `Source` | proposals; may auto-publish index records under `Permissions-Matrix:74` |
| `reviewer:*` | **humans only** | staff grant | `submission:review`, `merge:execute` | n/a |

Secrets are 32 random bytes shown once, stored as `sha256(SECRET_KEY + token)` — the existing verification-token pattern (`accounts/services.py:13-23`). Not a JWT: there is no key-management story and revocation must be instant. No credential for an unverified email — though note the gate is currently vacuous (0 verified rows), so checking that verification mail delivers precedes building any of this.

### 3.2 Scopes and per-subject checks

`catalog:read`, `submission:write`, `submission:read_own`, `submission:review` (human), `vocabulary:propose`, `collection:write` (own only), `export:read`, `admin:*` (human). Scope is necessary but not sufficient: `submission:write` on a subject the principal can see is not permission to write to a draft (`SUBJECT_NOT_PUBLIC`). `service:import` credentials carry a `source_scope` and reject evidence outside the approved manifest — the API form of "approved service account for a named source and field scope" (`Permissions-Matrix:55`).

### 3.3 Delegation and revocation

Every submission stores `operator_id`, `principal_id`, `run_id`, `credential_id` denormalised at write time, so revoking a credential never orphans attribution (same reason `WorkRelationship.source` is `PROTECT`, `models.py:529`). Operator verification = verified email + agent name + declared purpose + stored terms version. Domain verification (DNS TXT) is PROPOSED and deferred; it is the only honest way to distinguish a studio's agent from someone claiming to be one, and a checkbox must not fake it. Revocation is checked per request: held items are withdrawn, pending items stay pending, **approved facts are not revoked** — correcting them is a new submission, the same rule that applies to humans.

### 3.4 What is auto-accepted: nothing, in v0

Never auto-accepted by anyone: relationship edges (1,062 already pending), anything reading as a rights claim (`models.py:591-595`; `rights_provenance` states OMA does not adjudicate rights), merges (`services.py:24-26`), vocabulary, and review policy.

A later deterministic candidate: adding an `ExternalIdentifier` whose `(scheme, value)` already appears verbatim on that work's stored `SourceRecord` — a restatement, not a claim. Even that should first ship as a reviewer batch action ("accept all 200 restatements"), which saves the same time, keeps a human in the loop, and *produces* the acceptance data needed to justify automation. With 0 proposals, 0 revisions, and 0 `reviewed` provenance rows, automated approval is not policy, it is a guess.

### 3.5 One authorization function

`can(principal, operation, subject) -> Decision`, called by browser views, admin actions, commands, and API. The idea already exists in four copies — `_can_publish` (`views.py:253`), `_verified_submission_allowed` (`views.py:473`), `_require_merge_permission` (`services.py:24`), `has_perm("catalog.review_contributionproposal")` (`models.py:776`). Four copies is how an API ends up with a fifth that disagrees.

---

## 4. Reader and API experience

### 4.1 What can actually be served

- **No search index.** `search()` loads *every* candidate into Python (`discovery.py:67-80`, `presentation.py:71-88`). Measured this session: `q=hamlet` → 45 matches in **4.05 s / 77 queries**; `dracula` 2.93 s; `the` → 2,433 matches in 2.96 s, over 6,242 candidates. This already broke production once (500s past ~1,000 agents; `CURRENT.md`, 2026-10-28) and was fixed by batching, not indexing.
- **No full-text field.** `title` (300 chars) and prefix-over-words with alias/creator fallbacks; five rank buckets, distance capped at 40 (`discovery.py:64`).
- **Type filtering is also a scan** — `filter_public_type` calls `public_type_code` per work, which re-reads supplier payloads (`discovery.py:50-59`, `presentation.py:24-45`).
- **Traversal is cheap and already API-shaped:** one work's accepted neighbourhood, 12/page, constant queries (`connections.py:92-244`, `clear-work-connections.md:65-72`).
- **The corpus is small.** Public work text is ~420 KB; with 11,886 credits, ~21.9k identifiers, 42.3k evidence rows and 2,325 versions, a full public JSONL is low tens of MB (estimate from text-byte sums, not a built export).

So v0 should be **snapshot plus traversal, and no search promise** — which contradicts the page map's ordering, deliberately: a search endpoint inherits the page's worst property and loses its throttling.

### 4.2 Resources

`works/{id}` (+ `/relationships`, `/versions`, `/access-links`, `/history`), `agents/{id}` + `/works`, `lookup?scheme=&value=`, `changes?since=`, `collections/{id}`, `vocabularies/{name}`, `contract`, `errors`, `policy`, `snapshot/{date}.jsonl.gz` + `manifest.json`. Each maps to a table or module that already exists, except `changes` (§4.5) and the snapshot builder.

### 4.3 Identity

`Work.pk` is canonical and already in the URL (`works/<int:pk>/<slug:slug>/`, `catalog/urls.py:17`; "stable numeric IDs are authoritative", `Page-and-Action-Map:36`). Three hazards the API must handle:

1. **Slugs are not unique** — no unique constraint (`models.py:27`); I measured **6 duplicate slug values**. Rule: `id` is the key; slug is opaque and ignorable.
2. **Slugs mutate** — an approved title correction re-slugs (`models.py:838-840`), so a slug-bearing URL is not a stable citation. Return both `href` and `canonical_url`; clients key on `id`.
3. **Merges** — `WorkRedirect` gives old→canonical (`models.py:127-156`, `services.py:96-151`) and pages 301 (`views.py:193-196`), but there are **0 rows**, so it is unexercised. Rule: a merged id returns **200** with `status: "merged"` and `canonical_work_id` — an agent must learn its target moved, not silently write to the wrong row.

`lookup` must return `ambiguous: true` with candidates, because identifier uniqueness is a **convention, not a constraint**: `unique_work_scheme_value` is scoped to `(work, scheme, value)` (`models.py:648-654`). I measured 0 cross-work duplicates today; nothing prevents them. Do not add UUIDs or a second scheme.

### 4.4 Pagination and totals

Keyset cursors for `works`, `changes`, `submissions` (`?cursor=&limit=` encoding the last `(sort_key, id)`), because offset paging (`views.py:161`, page size 30) shifts under inserts. `total` is **not** free: cheap for `visibility='public'`, a full scan for search or type filters, so return `count` only when computed and `{"count_available": false}` otherwise — never a silent estimate. Page size default 50, max 200, clamped with `"clamped": true`. `sort` is an allowlist (`id`, `title`, `-first_publication_year`), mirroring `discover()`'s existing habit of ignoring invalid sorts (`views.py:152-158`).

### 4.5 Changes feed

`LibraryEvent` is a good substrate and the wrong contract: indexed, `kind`, before/after JSON, dedup key, 3,869 rows (3,777 `relationship_added`, 69 `corrected`, 3 `removed`, 20 `collection_added`) — but it is **per-follower** (`library.py:76-101`) and deliberately excludes saves, annotations, title/description edits, and merges (`personal-library.md:26-28`).

PROPOSED `GET /api/v0/changes?since=&types=`: an append-only `change_log(id BIGSERIAL, entity_type, entity_id, op, changed_fields[], before_hash, after_hash, actor_class, at)` written in the mutation transaction. Cursor = last `id` (monotonic, no clock skew). Coverage includes merges as tombstones `{old: n, canonical: m}` and submission decisions. Entities that are now draft or suppressed appear as `{op: "redacted"}` — the API form of the boundary already enforced at `library.py:87-89`. Retention 90 days hot, then manifests.

### 4.6 Versioning

URL major `/api/v0`; contract finer (`oma-contract/2026-11-1`) and echoed per response. Within a major, additive only; removing a field, changing a type, renaming a code, or tightening validation is breaking. `Deprecation`/`Sunset` headers (RFC 8594), a registry at `/api/v0/deprecations`, minimum 90 days, dual-serve. Vocabulary versions separately because codes grow with sources. `generated_from` lets a client detect a changed validator even when the version did not.

### 4.7 Machine-readable uncertainty

**Dates** — never a bare ISO string:

```json
{"text": "1965-04", "year": 1965, "precision": 10, "kind": "publication",
 "kind_label": "Source publication date", "meaning_verified": true,
 "source_url": "https://…", "evidence_state": "imported"}
```

`date_kind` across public works: `publication` 4,977, `release` 1,883, `first_performance` 326, `inception` 116, `production` 24, `first_release` 7, `first_publication` 1, `recording` 1, `unknown` 117. Precision in `date_evidence`: 4,346 year, 471 month, 1,979 day, 656 absent. `date_label` already downgrades to "Date (meaning unverified)" when evidence text does not match the displayed text (`models.py:109-117`); the API must expose that refusal, not flatten it. **Trap:** the column is `first_publication_year`, but 4,977 works record `kind='publication'` — a *source* date. The response key must be `date` with an explicit `kind`; `first_publication_year` must not appear in the API at all.

**Relationships** — `review_status` (no `rejected` state exists), `review_recorded: bool`, `scope_note`, `authorization_statement` (empty unless attributed, `models.py:591-595`), `evidence_source`, `evidence_retrieved_at`. All 4,504 accepted edges have no recorded reviewer, so `review_recorded` is `false` for every one: say so rather than print a "verified" badge.

**Quality flags** — `publication_warnings()` already returns stable codes (`no_date`, `no_creator`, `generic_type`, `long_title`, `placeholder_title`, `demo_work`; `publication.py:17-25,42-58`). Export per work; free, already implemented.

**Confidence** — client-declared only. Reviewer acceptance is not a probability; do not multiply two uncertainties into a third number nobody can interpret.

### 4.8 Eight queries

1. **"What is this film based on?"** → `GET /works/1234/relationships?direction=outgoing&category=derivation`, with direction-appropriate labels: the `adapted-from` inversion is computed (`connections.py:33-44`), so clients rendering stored labels show "Adapted into" backwards.
2. **"Which works adapt this novel?"** → `GET /works/5678/relationships?direction=incoming&category=derivation`. Often empty: 42.6% of browsable works have no accepted edge.
3. **"Everything by this creator"** → `GET /agents/4321/works?role=author&cursor=`. **No page exists**; the clearest missing surface, with 13,124 agents and 11,886 public credits.
4. **"What editions and translations exist?"** → `GET /works/5678/versions?include=releases`. 7,643 versions / 6,578 releases, but only 1 `edition-of` edge, so cross-work comparison is not answerable yet.
5. **"Where can I read or watch this, and has anyone checked?"** → `GET /works/1234/access-links?active=true` with `last_checked`, `reviewed_at`, `restrictions`. Bluntly: 32 links, 0 ever reviewed, 20 `catalog` (reference, not access), 12 `full`.
6. **"What changed since Tuesday?"** → `GET /changes?since=8841&types=work,relationship`. 3,777 of 3,869 existing events are edge additions — a client must know that before reading the feed as editorial activity.
7. **"Every public film with a derivation edge, as a file"** → `GET /snapshot/2026-11-01.jsonl.gz` + manifest, not a filtered list endpoint: both filters are full scans and cannot be cursor-paged stably.
8. **"Is this identifier the same work?"** → `GET /lookup?scheme=ol_work&value=OL123W` → `status: live|merged|ambiguous`; the only endpoint where ambiguity is a first-class answer.

### 4.9 Out of v0

Search, write APIs beyond §2, webhooks, GraphQL, streaming, and anything returning rating, popularity, or recommendation scores. None of those concepts exist in the schema, and inventing them in an API is how a catalog acquires a fake epistemic layer.

---

## 5. Views worth building

| Question | Today | Verdict |
|---|---|---|
| What connects to this work? | grouped list, timeline, filters, pagination (`connections.py`) | works |
| When did its afterlives happen? | timeline with highlights (`ranking.py:75-120`) | works; undated works dropped (`connections.py:124`) |
| How sure are we of its date? | `date_label`/`date_summary`, provenance panel | works, under-exposed in the API |
| Why does OMA say this title/type/date? | `_provenance.html`, three fields only | partial |
| Everything by this creator | **nothing** | missing |
| Compare editions/translations | **nothing**; inline per work | missing, data-poor (1 `edition-of`) |
| Browse a type | works, but ~3 s and a scan | slow |
| Export a collection or slice | **nothing** (`annotated-collections.md:48`) | missing |
| Review a queue | admin form, one at a time | missing as a page |

**Build, in order:** (1) public bulk export + snapshot manifests — cheapest, unlocks downstream tools, sidesteps search, makes citations reproducible; (2) public work-history page (§2.8) — data exists, only visible in admin, and it is the project's differentiator; (3) review queue page with conflict grouping, corroboration counts, and reason codes — a prerequisite for any agent scale; (4) creator/organisation page, promised since `Page-and-Action-Map:43` and absent despite 13,124 agents; (5) canonicalisation report (merged ids, 6 slug collisions, identifier conflicts).

**Do not build:** a force-directed graph (6,242 nodes where 2,661 have degree 0 and 228 have degree ≥5 is a picture of absence); a dashboard of counts ("13,878 works · 1,062 pending" changes no decision and is stale in a week — put counts where the decision is); agent-activity dashboards (vanity metrics that reward the behaviour §2.9 is pricing); a per-contributor "trust score" (false precision, gamed within a month — use coarse classes); recommendations (deferred in `AGENTS.md`; no ratings, no reading history, 0 `WorkFollow` rows).

---

## 6. Shared versus generated

Rule: **if it changes what the catalog asserts, it is shared and reviewable; if it changes one reader's view, it is per-account or computed; if it is an editorial decision, it is shared and attributed to a human.**

| Shared | Per-account | Computed on demand |
|---|---|---|
| work identity, identifiers, merges | saved works, follows, reading state | type labels (`public_type_code`) |
| edges + review status | | date display, `date_label` |
| vocabulary (`Term`, `RelationshipType`, `WorkType`) | | relevance ranking, timeline highlights |
| provenance ledger (`FieldEvidence`, `SourceRecord`, `ContributionRevision`) | | counts, dashboards |
| access links, public collections + order | | recommendations |
| change log; principals/credentials (secrets never exported) | | exports (**payload**; the manifest and hash are stored) |
| `FeaturedWork` (human editorial) | | |

Two consequences. `public_type_code` recomputed per request (`presentation.py:24-45`) is why type filtering scans; the fix is a cached column, not a new API concept. And any personalised feature that alters a *public* ordering converts private data into shared fact — never let a recommendation change a public surface.

---

## 7. Critique: five weakest assumptions

### 7.1 "The pipeline exists, so contribution can scale."

**Why it fails:** 0 proposals ever, 0 verified accounts, one superuser, and review is a Django change form. The bottleneck is throughput, not submitter tooling — every quota in §2.9 rests on a number nobody has measured.

**What settles it:** decisions/hour for one reviewer, median time-to-decision, acceptance rate, over ≥100 decisions.

**Cheapest measurement:** process 20 of the 1,062 pending proposals in admin with a stopwatch. One afternoon, no code, and it yields the only number that matters.

### 7.2 "Agents will add information the catalog lacks."

**Why it fails:** the problem is *unresolved* facts, not absent ones. 1,062 edge proposals pending, 1,041 import items `conflicted`, and 4,504 accepted edges with no recorded reviewer — `FieldEvidence.origin` is 41,740 `imported`, 609 `unrecorded`, **0 `reviewed`**. More submitters widen an input funnel whose output is blocked. Agents reading the same Open Library and Wikidata records the importer already read are not independent; they restate one source. The result is a catalog that looks richer while the share of claims anyone verified falls.

**What settles it:** of 100 contributions, the split between (a) resolving an existing conflict, (b) values no current source states, (c) duplicates of stored claims.

**Cheapest measurement:** one SQL pass over the 4,504 edges for `evidence ? 'reviewed_at'` — ten minutes, and it says whether provenance is real or decorative.

### 7.3 "The catalog is queryable, so an API is a thin wrapper."

**Why it fails:** pages are fast because they are bounded (one neighbourhood, 12 rows, constant queries). Search and type filtering are Python scans: **2.9–4.1 s, 77 queries** over 6,242 candidates, and they already caused a production-wide 500. A page pays that once for one human; a crawler pays per request. Wrapping the page in JSON imports its worst property and drops its throttling.

**What settles it:** p95 latency at 5 concurrent clients on search, and tolerance for a full scan per request on a single worker.

**Cheapest measurement:** 100 sequential then 5-concurrent requests to `/discover/?q=the` on a staging copy.

### 7.4 "Identifiers are stable enough to cite."

**Why it fails:** the merge path has **0 rows** — `WorkRedirect`, the 301, and the merge-time rewrites of saves, follows, credits, versions, identifiers, edges, entries, and proposals (`services.py:96-151`) are untested against real data. Slugs collide (6 values) and mutate on title approval. Identifier uniqueness across works is unenforced. A client caching "the slug URL" breaks silently on the first title correction or merge — both planned operations.

**What settles it:** three real merges and three title corrections, then replay a client's cached URLs and identifiers and count what still resolves correctly.

**Cheapest measurement:** merge two demo works and one duplicate pair, correct one title, re-run the eight §4.8 queries against the pre-change cache.

### 7.5 The ambition: "OMA as a Galaxy where agents are primary contributors"

**It is empirically not a galaxy.** Among 6,242 browsable public works, **2,661 (42.6%) have zero** accepted relationships, 2,185 have one, and only **228 (3.7%)** have five or more. That is a long tail with a few well-edited islands around ~50 `editorial` records. Agent-proposed edges would mostly add degree-1 links to works nobody reaches — raising counts, lowering average value, and each still costing a review.

**The economics are backwards.** Agent contribution is sold as free supply; it is not. Every submission buys reviewer attention, and OMA has one part-time human. Value per accepted fact falls down the tail (a corrected date on an obscure record has near-zero reader impact) while review cost per fact is constant — so marginal cost per unit of reader value *rises* with volume. The existing 1,062-item backlog is ~35 reviewer-days; "primary contributors" would make backlog the permanent state.

**Governance is absent, and the framing hides it.** The matrix grants capabilities per account (`Permissions-Matrix:13-26`) with no concept of a fleet. If any agent class gets automated acceptance, whoever runs the largest fleet shapes a public cultural catalog without passing a human gate — with one staff account and zero verified users, i.e. no institution able to arbitrate between two operators. Add data rights: OMA is scrupulous about not inferring rights (`models.py:591-595`, `work-access.md:11`), yet an agent summarising a scraped page creates derived text of unclear provenance — the exact risk avoided so far — and the ledger cannot even represent it, since `FieldEvidence.origin` only has `unrecorded | imported | reviewed` (`models.py:956-957`). The galaxy framing makes the fleet the unit of power while the ledger cannot describe what the fleet did.

**What settles it:** whether the current backlog changes any plausible reader answer. Sample 30 of the 1,062 proposals and ask, per item, if accepting it changes a question on a work that already has ≥1 connection.

**Cheapest measurement:** the degree distribution above, plus 30 hand-checked proposals against endpoint degree. Two hours, and it forces the real choice: **agents as force multipliers on a reviewed pipeline, or agents as primary contributors** — different products, and only the first is defensible at this size.

Cheap fix while it is still cheap: rename the concept to `principal`/`operator` before a line of API ships, or every future reader of this code must disambiguate "agent" from context.

---

## 8. The gate, and the first two experiments

Nothing in §2–§4 should be built before a scoped milestone; `AGENTS.md` forbids new infrastructure and AI enrichment without one, and the page map defers write APIs (`:148`).

**Milestone scope (PROPOSED):** public snapshot + `/api/v0/works/{id}` traversal + `/contract` + bounded `/queues` + credentials for `contributor:probationary` only, writing into the **existing** `ContributionProposal` table. No new submission model, no auto-accept, no search API, no webhooks.

**Experiment 1 — review throughput (1 week, no code).** Process 20 pending import relationship proposals in admin; record seconds/decision, acceptance rate, and how often the reviewer leaves the page to check a source. Output: the number behind every quota in §2.9, and a decision on whether the queue page precedes the API.

**Experiment 2 — does agent contribution beat the importer on the same source? (2 weeks, one source, one gate).** Take 50 public works with `no_creator`; have one `probationary` principal propose credits from a source the importer already ingested. Compare precision against reviewer adjudication, reviewer-minutes per accepted credit, and duplicate rate against existing `Credit` rows. Success: ≥70% precision at ≤3 reviewer-minutes per accepted credit, with duplicates low enough that corroboration collapsing is not doing the work. If it fails, the honest conclusion is that OMA needs better triage of what it already imported, not more contributors.

Both are cheap, both produce numbers instead of opinions, and either can kill the larger plan — which is why they go first.
