# OpenMediaAtlas: permissions and publication policy

Draft for review · 20 September 2026 · Companion to the DBML and page map

## Decisions incorporated

- Thin records may be public if they meet a minimum identity/evidence standard. Completeness is not the publication gate.
- Versions normally appear inside work pages. A notable translation/cut, especially one that is itself adapted, can receive a dedicated page while remaining a version in the data model.
- OpenMediaAtlas controls the shared vocabulary. Users can propose new terms, aliases, and term assignments; they do not create new public filter options instantly.

These decisions supersede the corresponding open questions in the previous page-map draft. The existing DBML has not been changed by this document. Other policies below are proposals.

## 1. Roles and scoped permissions

Use capabilities granted to accounts, not a single ladder in which every higher role automatically sees everything. In a small team one person may hold several roles.

| Role | Purpose |
|---|---|
| Visitor | Read public material. |
| Member | Manage own content and propose catalog changes. |
| Catalog reviewer | Review record changes and evidence; publish qualifying records. |
| Vocabulary curator | Maintain terms, aliases, definitions, and hierarchy. |
| Community moderator | Handle reports, discussions, and account restrictions. |
| Rights reviewer | Access assigned private claim evidence and evaluate representation claims. |
| Administrator | Grant capabilities, manage imports and exceptional destructive/sensitive actions. |
| Service account | Run a named, limited import or enrichment process. No blanket administrator authority. |

Verified representation is a scoped badge/relationship, not a staff role. A publisher, creator, or rights holder does not acquire exclusive control of a public catalog page.

## 2. Action matrix

“Propose” means submit for review. “Own” means only the acting user's resource. Staff powers require an explicit capability, even when the administrator account performs the action.

| Action | Visitor | Member | Authorized staff / service |
|---|---|---|---|
| Read public catalog, public history, public lists | Yes | Yes | Yes |
| Save/rate/request adaptation/manage private notes | No | Own | Staff cannot routinely read private notes |
| Create/edit/delete a personal list | No | Own | Moderator can suppress public visibility for policy violations, with audit |
| View private lists and saved searches | No | Own | Exceptional support access only if explicitly authorized and logged |
| Add a new work/creator/version | No | Propose | Catalog reviewer publishes after gate; approved import can publish eligible records |
| Change titles, dates, credits, relationships | No | Propose | Catalog reviewer accepts/applies with revision history |
| Suggest term assignment | No | Propose existing term | Catalog reviewer accepts assignment |
| Create/rename/merge a shared term | No | Propose | Vocabulary curator only |
| Promote a version to a dedicated public page | No | Propose with reason | Catalog reviewer; presentation change is recorded |
| Change relationship authorization/rights statements | No | Propose with evidence | Reviewer with rights-publication capability; unknown remains acceptable |
| Submit a representation claim | No | Own submission | Rights reviewer accesses evidence; public result exposes only appropriate scope |
| Upload images | No | Propose with source/reuse basis | Authorized reviewer accepts; validation and storage rules apply |
| Publish ordinary discussion comments, when enabled | No | Yes, subject to abuse checks | Moderator can hide/lock; new/suspicious accounts can be queued |
| Edit own comment | No | Own, marked edited | Moderator may hide, not silently impersonate the author |
| Approve own catalog proposal | No | No | Second reviewer preferred; sole-maintainer exception explicit and auditable |
| Merge duplicate records | No | Propose | Dedicated merge capability; preview conflicts and preserve redirects |
| Restore earlier catalog content | No | Propose | New accepted revision, never erase intervening history |
| Suppress catalog record or sensitive evidence | No | Report | Explicit moderation/privacy capability with restricted audit |
| Grant staff roles / suspend service token | No | No | Administrator; cannot self-grant through profile edits |
| Run bulk import | No | No | Approved service account for named source and field scope |
| Execute model-generated enrichment | No | No | Service submits candidates; no autonomous rights verdicts or merges |

No action should gain more power merely because it comes through an API. Browser, admin UI, background job and API use the same authorization rules. Test ownership on every resource, not just at login.

## 3. Minimum public-record gate

### Works

Require:

1. A usable title/name and a supported broad form, even if detailed classification is unresolved.
2. At least one traceable source supporting existence and identity; a creator's first-party announcement may support a clearly labeled planned work.
3. Enough distinguishing evidence to identify the item: a reliable external identifier or a meaningful combination of creator, date, publisher, container, or source link. Unknown author/date alone does not disqualify an anonymous historical work.
4. Duplicate screening performed; obvious collisions and ambiguous source matches are queued rather than guessed.
5. No unapproved copied description, unsafe upload, private evidence, or unsupported rights/verification badge in public output.

Do not require a cover, summary, rating, adaptation, complete credits, English original language, or known rights status. Public records may be sparse, but must identify something useful. Display “Index record” with a plain explanation; do not imply editorial review of every field.

Imported records passing an approved deterministic gate may publish automatically as index records; spot-check each new adapter before enabling that. Member-created records initially use human review. Automated publication is not the same as marking citations “accepted.”

### Other records

- Agent: name, kind, traceable identity source, duplicate screening. A profession or a birth date need not be known.
- Version/release: known parent, appropriate label, source supporting the distinction. An unresolved imported version is allowed as an explicit container, not as a fabricated named translation.
- Relationship: two resolved endpoints, allowed relationship type, evidence and scope. A public work does not make every proposed connection automatically public.

## 4. Dedicated version pages

Proposed canonical route: `/versions/{id}/{slug}` when promoted; otherwise show an expandable row and anchor on the work page. Always label the page “A version of [work]” and expose its language, translator/cut, date, and distinct credits.

Promotion reasons include substantial independent interest, well-documented distinct identity, or becoming an identifiable source for later work. Popularity is not a rigid numeric threshold. Promotion must not generate a duplicate work just to obtain a URL.

Both old work-page anchors and direct record IDs remain usable after promotion. The adaptation relationship can continue to identify the source work plus `source_version_id`; display the exact version when known. Version-specific relationships beyond “source for an adaptation” need further modeling before assuming the current schema covers them all.

Needed schema addition: a reviewed presentation setting such as `page_mode = embedded | standalone` on versions, plus the reason/history. This setting is distinct from record visibility.

## 5. Vocabulary workflow

1. Contributor searches existing terms. Search matches preferred labels and approved aliases.
2. If none fit, propose a new term with vocabulary, definition, one example work, and explanation of the missing distinction.
3. Curator accepts a distinct term, maps a synonym to an existing term, asks for clarification, or rejects it with explanation.
4. Approved mappings normalize imported tags; unknown source terms remain raw/staged, not thousands of new public filters.

Example: “sci-fi,” “SF,” and “science fiction” may resolve to one genre term after context review. “Unsettling” and “horror” are not synonyms: one is tone, the other genre. Do not merge labels across vocabularies solely because their spelling matches.

Needed additions: term aliases, term proposal/review records, and canonical term redirects or merge mappings. Changing a parent/hierarchy needs cycle checks and review of filtering consequences. Renaming should preserve old URLs/search matches. The current `terms` table alone does not implement these workflows.

## 6. Private information and audit boundaries

- Rights evidence, emails, login credentials, raw abuse reports and private notes never enter public catalog snapshots or exports.
- Public attribution may show username, timestamp, and a sanitized edit summary. Hide personal data accidentally included in an edit reason.
- Accepted catalog history is append-only in normal use. Privacy/legal redaction is a separate privileged action with a restricted audit trail.
- Reviewer decisions state what was verified: identity, representation, a source statement, or catalog accuracy. These are different claims.
- API rate limits and spam controls complement permissions; they do not establish factual trust or prevent all copying of public data.

## 7. Concrete permission tests

An ordinary member cannot approve their own correction, change another user's list, read private evidence through a guessed ID, create a canonical genre by submitting free text, or use an API call to bypass the queue. A verified producer cannot erase unfavorable discussion or overwrite community credits. An importer cannot overwrite a protected human field or mark its own uncertain match verified. A community moderator cannot inspect rights documents unless separately granted that scope.

Audit records for term changes, moderation and role grants, plus scoped service credentials, remain implementation work. This matrix defines intended behavior rather than claiming the current schema or app already enforces it.
