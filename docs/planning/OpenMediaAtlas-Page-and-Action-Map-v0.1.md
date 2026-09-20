# OpenMediaAtlas: page-and-action map

Draft 0.1 · Companion to `OpenMediaAtlas-v0.1.dbml` · 20 September 2026

**Purpose:** specify what people can see and do, without committing to a framework. This is a proposed product scope, not a claim about what the existing app already implements.

OpenMediaAtlas is a catalog for discovering works and understanding their adaptations and related creations. The public experience should feel like a welcoming, information-rich media catalog. Contribution and review tools support that experience.

## 1. Scope for a useful first release

**The complete first journey:** find a work → understand its important connections → follow one → save it or propose a sourced correction → a reviewer approves the correction → the change and its attribution appear publicly.

| Priority | Include |
|---|---|
| Launch | Browse/search, work pages, creator/organization pages, embedded versions/releases, modest relationship map, outbound links, accounts, saves/adaptation wants, simple lists, proposed edits, review queue, revision history, basic import oversight. |
| Next | Discussions and written reviews, saved searches, creator project declarations, rights-holder claim workflow, richer list discovery, broader public API. |
| Later | Notifications, personalized feeds, multi-axis ratings, payments/licensing transactions, crowdfunding, large graph explorer, recommendation analytics. |

If a feature already works, keep it where it helps. “Next” means it need not block the first release; it does not mean deleting functioning features. Start with a manageable set of well-linked records rather than publishing every raw import.

## 2. Visitor and contributor roles

| Role | Typical actions | Boundary |
|---|---|---|
| Visitor | Search, browse, inspect public records/lists/history, follow read/watch links. | Cannot mutate public data; private/unlisted content is treated separately. |
| Member | Save, rate, request adaptations, create lists, propose changes; later discuss and declare projects. | Ownership of a list does not grant authority over catalog records. |
| Trusted contributor | Initially the same proposal route, with a visible contribution history. | Direct editing is a later policy choice, not automatically earned by edit count. |
| Reviewer | Review factual edits and evidence, request clarification, compare conflicts, approve appropriate changes. | Must have an explicit permission; cannot infer rights ownership from a claimant's identity. |
| Administrator | Manage roles, suppression, sensitive merges and escalations, imports, abuse response. | Sensitive actions are logged; public edits still produce history. |
| Verified representative, later | Display a scoped representation badge and submit statements for the represented entity/work. | Does not own the public page or gain exclusive editing rights. |

Accounts and passwords belong to the authentication framework. `users` in the diagram is only its public-profile subset. These permissions must be enforced on the server, including API access.

## 3. Public page inventory

Routes are illustrative; stable numeric IDs are authoritative and readable slugs are optional. Versions and releases are records, not automatically new public pages.

| Page / route | Main information | Main actions | Data behind it | Priority |
|---|---|---|---|---|
| Home `/` | A short explanation, search, a few curated collections and interesting connections. | Search; browse a collection; discover a connected work. | `works`, `lists`, `list_items`, relationships | Launch |
| Discover `/discover` | Results with title, format, date, creator, image/fallback, selected tags and connection counts. | Query, filter, sort, open, save; share current URL. | Works, terms, languages, credits, identifiers | Launch |
| Work `/works/{id}/{slug}` | See section 4. | Follow connections; read/watch; save; want an adaptation; add to list; suggest correction. | Most catalog tables | Launch |
| Creator or organization `/creators/{id}/{slug}` | Name, aliases, short bio, image, links, credited works grouped/filterable by role. | Open works; filter credits; suggest correction. | `agents`, `credits`, `credit_roles`, names, assets | Launch |
| List `/lists/{id}/{slug}` | Title, curator, description, ordered works and annotations. | Open works; share if permitted; owner edits/reorders. | `lists`, `list_items`, `users` | Launch |
| Profile `/people/{username}` | Public bio, public lists, accepted contributions; public activity only by choice. | Browse contributions and lists. | Users, revisions/proposals, lists | Launch |
| Revision history `/records/{id}/history` | Accepted edits, dates, public attribution and concise change summaries. | Compare revisions; propose a correction or restoration. | `record_revisions`, safe source references | Launch |
| Discussion `/discussions/{id}` | Topic, replies, spoiler controls, status. | Reply, edit own comment, report; moderators lock/hide. | Threads/comments; reporting workflow requires an addition | Next |
| Global connections explorer | Potentially a large, filterable graph. | Explore across several hops. | Work relationships | Later |

A creator page can reuse the search-results component, but retains a stable identity, biography, credits and contribution history. Publishers and studios use the same page template with organization-specific labels.

## 4. Work-detail page, in reading order

### A. Identity and primary actions

- Cover/poster or intentional typographic fallback; never invent an official-looking cover.
- Title, subtitle, form, original date when known, principal credited creators.
- Short description; index/editorial depth label with a plain-language explanation.
- Save, “Want an adaptation,” add to list, and copy page link.
- Read/watch/play links when known. Their absence should not hide the work.
- Unknown information stays omitted or explicitly unknown; do not turn missing values into confident facts.

### B. Important relationships

One hop centered on the selected work. Aim for about 3–7 cards initially, with a “View all” list for overflow. This is a readability target, not a storage restriction.

| Area | Behavior |
|---|---|
| Based on | Show direct source works. If several sources matter, show multiple cards. |
| Current work | Visually anchored card; do not repeat the entire header. |
| Adaptations / remakes | Show directly derived works, using precise labels. |
| Other connections | Separate sequel, prequel, inspiration, trailer and reference links. Do not mix weak allusions into the main adaptation map. |
| Evidence | A relationship's detail popover explains the connection and links to its sources and correction action. |

Visual arrows may run source → derived work even though `adapted_from` is stored child → source. The renderer must interpret relationship types rather than draw every foreign key literally. On mobile, use stacked cards with verbal labels. Choose default connections by relevance and useful diversity; document the sort, and avoid presenting inclusion as proof of quality or official status.

Clicking a connected work opens/recenters on that work. Do not recursively expand the whole graph by default. Two films based on one novel are not necessarily remakes of each other.

### C. Details, credits, and classifications

Compact labeled rows for form, languages, genre, tone, setting, length, status, and relevant production information. Show only applicable fields. Full credits expand beneath principal credits; people and organizations link to their pages. Tags link to a filtered discovery URL.

Subjective tags such as “unsettling” need editorial/community attribution, not the visual authority of a publication date. Exact runtime belongs to a version; avoid displaying an arbitrary cut's runtime as universal.

### D. Versions and releases

Expandable groups: original text, named translations, cuts or revisions. Inside each, show releases with relevant publisher/distributor, date, format, identifiers and availability. A user should not need to learn the word “expression.”

Use a stable URL fragment such as `#version-1103` to share a version within the work page. The UI must expand the relevant group when that fragment is opened. Release anchors work the same way. Canonical work pages remain the navigation destination.

### E. Rights and participation

Show a short rights summary only when evidence supports its scope. Example wording for a mock record: “Original text: public domain in the US; translation rights differ.” Open a panel for jurisdiction, component, source, review date, and uncertainty.

A reviewed source is not a legal guarantee. Do not convert an “authorized representative” badge into “free to adapt.” Creator project declarations, when added, are labeled as declarations and never reserve an underlying work.

### F. Community and record maintenance

Relevant lists and aggregate adaptation demand; later ratings/reviews and discussions. Footer: suggest correction, add missing relationship, inspect history, report a problem. Attribution should be available without making the page primarily an editor scoreboard.

## 5. Personal and contribution pages

| Page / surface | Actions and expected result | Priority |
|---|---|---|
| My library `/me/library` | Saved works, progress, ratings and private notes. Privacy choices are explicit; private notes are never exported as public profile content. | Launch |
| My lists `/me/lists` | Create/edit list, change visibility, reorder/remove entries, share eligible list. | Launch |
| Propose edit `/records/{id}/suggest` | Prefilled form; change selected fields, explain why, attach sources; see a preview. Submission records the base revision. | Launch |
| Add missing work `/contribute/work` | Search for duplicates first; create a draft with minimum identity and source information. No instant public index page. | Launch |
| Add connection, from a work | Choose existing target, exact relationship type, optional source version, explanatory scope and evidence. Preview the displayed arrow. | Launch |
| My contributions `/me/contributions` | Pending, accepted, rejected, and clarification-needed proposals; see explanations and revise/resubmit. | Launch |
| Saved searches `/me/searches` | Name current query/filters, rerun, edit or delete. Saved search does not imply email alerts. | Next |
| Claim representation | State whom the member represents and for which component/territory; submit private evidence. | Next |
| Project declaration | Describe an intended adaptation and optional existing resulting-work record; update status or withdraw. | Next |

For new people/organizations needed by an edit, allow a draft identity rather than forcing contributors to invent a resolved match. Bundled creation of a work, creator and relationship needs a coordinated proposal mechanism; the current schema does not yet model a full proposal bundle.

## 6. Reviewer and administrator pages

| Page | Must display | Available decisions |
|---|---|---|
| Review queue | Proposal kind, target, author/origin, age, sources and conflict indicator. | Claim/review an item; filter by area and status. |
| Proposal review | Current value, proposed value, base revision, evidence, submitter explanation. | Accept, reject with reason, request clarification; require rebase/manual resolution if the record changed. |
| Duplicate/merge review | Both records, identifiers, conflicting fields, linked versions, credits and relationships. | Reject match or choose canonical record and resolve conflicts. Preserve old IDs as redirects. |
| Import dashboard | Run status, last checkpoint, new/updated/skipped/ambiguous counts and failures. | Resume/retry a safe batch, inspect ambiguous matches, publish eligible records through review rules. |
| Rights-claim review, later | Private evidence, claimed role/scope, existing rights statements and conflicting claims. | Verify scoped representation, reject or request evidence; separately propose public factual changes. |
| Abuse and visibility controls | Reports, target, reason, previous action and responsible moderator. | Hide/lock/suspend with reason; review appeals. Dedicated report/action tables still need design. |

Django admin or another generic admin can cover early internal CRUD, but a raw edit form is not a safe substitute for a merge or conflict-review screen.

## 7. States every launch flow must handle

| Situation | Expected behavior |
|---|---|
| No search results | Explain which filters apply, allow removing them, and offer a missing-work contribution. |
| Thin imported record | Show available facts with an index label; no fabricated summary or inferred rights badge. |
| Missing cover | Deliberate fallback with title and medium; no broken image icon. |
| Failed save/submission | Preserve entered text and explain failure; retry must not create duplicate proposals. |
| Concurrent edit | Show what changed since the proposal began; never silently overwrite accepted edits. |
| Disputed relationship | Keep the disagreement visible or withhold the connection according to policy; do not equate “disputed” with “false.” |
| Deleted/merged record | Redirect merges to the canonical record; suppression gets an appropriate public response without revealing private moderation information. |
| Private list/search/evidence | Server-side access denial, including API and direct URL access. |
| Stale availability link | Show last checked date where useful and provide a report action; do not assert current availability indefinitely. |

## 8. Behavior, not a mandate for full-page reloads

Filters, save/want actions, version expansion, correction forms and pagination can update part of a page. URLs preserve search/filter state and browser back behavior. Public record content is readable without requiring a graph widget. Forms have accessible labels, keyboard navigation, useful focus behavior, and visible errors.

Bulk metadata imports, enrichment, duplicate matching and image processing run outside ordinary page requests. Start with a documented read API that uses the same public visibility rules; write APIs and agent credentials are later scope. An API is not a bypass around review or privacy.

## 9. Decisions for Justin to review

1. Which actions matter most on the first work page: save, want adaptation, or explore connections?
2. Should all accepted relationship types be visible by default, or only strong derivations?
3. Are there any translations/cuts that deserve their own public page, despite the default embedded presentation?
4. Do trusted contributors eventually publish directly, and which changes always require review?
5. Should thin but correctly identified records be public immediately, or wait for a minimum useful set of facts?
6. Can all users create terms, or only suggest assignments from a curated vocabulary initially?
7. Which user activity should be public by default? Proposed default: lists and activity private until selected otherwise.

## 10. Demonstration that the first release works

- A visitor can find a novel, understand its relationship to a film, and follow a watch link without creating an account.
- A member can save it, create a public list, and share a URL that another browser can read.
- A member can propose a sourced adaptation connection; approval changes both relevant work pages and creates history.
- A duplicate import does not create another work; a changed import does not erase a human correction.
- A merge keeps incoming links working and does not lose a contributor's list entry.
- A work with unknown rights does not display permission to adapt.
- A private list, note, or rights-claim attachment stays private through every public route/API.

These are acceptance targets, not assertions that the current code already passes them.
