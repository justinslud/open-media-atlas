# Personal library, saves, follows, and updates

The account route `/account/` is now **My library**, with Saved works, My collections, Following, and Updates. Account verification settings remain on the same page. Existing collection management and public collection URLs remain unchanged; the connection browser and annotated collection editor from chunks 2–3 are preserved.

## Actions

- **Save** stores a work in the member's private library. Work pages, homepage cards, browse results, and saved-work rows show actual Save/Saved state.
- **Add to collection** uses the existing curated collection model and routes.
- **Follow** subscribes independently to supported changes inside OMA. Work and accessible collection pages offer Follow/Following controls; the library allows direct unfollowing.
- The current repository has no adaptation-want model or route; this chunk does not introduce or repurpose one.

The new POST endpoint `/me/library/action/<action>/<pk>/` accepts an explicit desired state (`active=1` or `active=0`). Unique database constraints and member row locking prevent duplicate subscriptions or saves. CSRF protection applies. An anonymous POST stores the action in the session and returns to a confirmation form after sign-in; GET never performs a mutation. Return URLs are validated. The progressive enhancement waits for confirmed success and reports network/HTTP failures in an accessible alert, leaving the previous state intact. Controls are outside card links and use native keyboard-operable buttons with pressed state and action labels.

Saved works support title/creator search and work-type filtering. Every library section uses 20-item pagination; Following distinguishes Works and Collections. Personal queries always use the authenticated member, never a supplied user ID. No public profile, activity broadcast, follower count, email delivery, or notification infrastructure is added.

## Exactly what creates an update

Tracking begins when this feature is installed; the migration does not backfill events.

1. A new direct relationship explicitly accepted through the staff relationship admin or community/import proposal approval, once both canonical endpoints are public.
2. An existing relationship changing from unreviewed/disputed to accepted, once both canonical endpoints are public.
3. A publicly accepted relationship's endpoints, relationship type, scope note, or source changing through a normal model save (the staff admin uses this path). Before/after values are retained.
4. A public relationship being deleted or losing accepted status.
5. A public, canonical work being added to or removed from a public collection, through the existing owner routes or ordinary model/admin operations. Changing an entry's collection/work represents a removal and an addition.

An editor approval involving draft endpoints is durably deferred until publication through `Work.save()`; the existing approved-endpoint admin action now uses that path. A pending approval withdrawn before publication generates no update.

Unreviewed proposals, rejected contributions, private collection membership, annotations, description/title edits, reordering, unchanged saves, evidence retrieval timestamps, fixture imports, bootstrap relationship loads, and canonical merges do not create updates. Ordinary creation of already-accepted relationships without explicit human publication is treated as a baseline/import, not a recent change. Use `relationship.save(publish_event=True)` for an explicitly approved new editorial relationship. `suppress_updates()` wraps existing fixture loaders and merge operations.

## Event and access safety

`LibraryEvent` is a shared structured event, rather than a row per follower. It references canonical works and collections and retains only a small relationship summary. Model saves and deletion signals write events inside the mutation transaction: rollback removes both. Existing relationship row locks and persisted before/after comparison deduplicate repeated saves; deterministic unique deletion keys deduplicate repeated deletion processing. Database uniqueness protects saves, follows, and existing collection membership.

The feed queries current subscriptions and events since each subscription began. Unfollowing removes those updates; refollowing starts a new window. Following both endpoints still returns one event. Every old/new endpoint must currently be public and canonical. Deleting an endpoint removes incomplete events. Collection visibility is checked before pagination/counts; public-to-private transitions hide the collection and its updates from members without access. Following never grants access. A fresh `public_since` timestamp on visibility changes prevents an old event from resurfacing with collection text changed during a private interval. Private collections remain followable by their owner or members with the existing explicit view permission, but only public membership changes enter the Updates feed. A revoked subscription can be removed by known ID without exposing the object.

Canonical merges move and deduplicate saved works and work follows onto the surviving work, without creating merge updates. Old events involving redirected endpoints are hidden.

## Migration and history limits

Apply `catalog.0014_medialist_public_since_libraryevent_collectionfollow_and_more`. It adds SavedWork, WorkFollow, CollectionFollow, LibraryEvent, the collection public visibility timestamp, and a deferred-publication flag on relationships. It initializes no historical events and needs no worker, external service, staging environment, or ingestion run.

The existing contribution history does not cover collection membership and staff relationship corrections/deletions, so this chunk adds the smallest shared mutation log for those operations. Django `QuerySet.update()` and `bulk_create()` bypass model saves and do not generate events; external SQL also bypasses tracking. Existing reorder/timestamp updates intentionally use bulk updates, while the publication admin was changed to model saves. Future publishing paths must use the tracked model methods. This feature does not replay arbitrary bulk catalog publications as new relationship activity. There are no read/unread badges or historical backfill.

## Verification

- Full suite: `DJANGO_DEBUG=true DATABASE_URL='' .venv/bin/python manage.py test --noinput` — 126 tests pass, including 24 focused library tests.
- Schema check: `DJANGO_DEBUG=true DATABASE_URL='' .venv/bin/python manage.py makemigrations --check --dry-run` — no changes.
- `git diff --check` — clean.
- Focused coverage: explicit save/follow state and uniqueness; authentication, CSRF, ownership and visibility; independent collection membership; accepted/rejected/deferred changes; duplicate deletion processing; mutation/event rollback; private transitions and current endpoint checks; personal isolation, search/filter/pagination; canonical merge preservation.
- Chromium/Playwright checked a 1440px desktop and a 390px mobile viewport against a separate SQLite database containing only synthetic test works, users, and collections. Verified anonymous save/sign-in continuation, saving and following independently, owner collection additions, staff-approved relationships, both update types, keyboard activation, linked-card navigation prevention, visible request failure/recovery, mobile browse Save visibility, and unfollowing. Inspected desktop/mobile screenshots and checked mobile overflow.
- Tests use SQLite. PostgreSQL row-lock behavior was not exercised in this environment.

## Local viewing

No hosted preview or staging service is created. Use a development database:

```sh
DJANGO_DEBUG=true DATABASE_URL='' .venv/bin/python manage.py migrate
DJANGO_DEBUG=true DATABASE_URL='' .venv/bin/python manage.py runserver 127.0.0.1:8000
```

Open `http://127.0.0.1:8000/`, sign in, save/follow a published work, follow a public collection, and visit **My library → Updates** after an owner membership change or editor-accepted relationship change. Existing local development users/works can be used; production data must not be used for automated tests.
