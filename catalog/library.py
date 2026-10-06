"""Shared, transactional events. Imports/merges explicitly suppress tracking."""
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import models

_tracking = ContextVar("library_tracking", default=True)


@contextmanager
def suppress_updates():
    token = _tracking.set(False)
    try:
        yield
    finally:
        _tracking.reset(token)


def tracking_enabled():
    return _tracking.get()


def relationship_snapshot(relationship):
    if not relationship or relationship.review_status != "accepted":
        return None
    from .models import Work
    ids = {relationship.from_work_id, relationship.to_work_id}
    if Work.objects.filter(pk__in=ids, visibility="public", canonical_redirect__isnull=True).count() != len(ids):
        return None
    return {"from": relationship.from_work_id, "to": relationship.to_work_id,
            "type": relationship.relationship_type_id, "label": relationship.relationship_type.label,
            "scope": relationship.scope_note, "source": relationship.source_id}


def record_relationship_change(before, after):
    if not _tracking.get() or before == after or not (before or after):
        return
    from .models import LibraryEvent
    event = LibraryEvent.objects.create(
        kind="relationship_corrected" if before and after else "relationship_added" if after else "relationship_removed",
        before=before or {}, after=after or {},
    )
    event.works.add(*{value[key] for value in (before, after) if value for key in ("from", "to")})


def record_membership(entry, kind):
    if not _tracking.get():
        return
    from .models import LibraryEvent, MediaList, Work
    if not MediaList.objects.filter(pk=entry.media_list_id, visibility="public").exists():
        return
    if not Work.objects.filter(pk=entry.work_id, visibility="public", canonical_redirect__isnull=True).exists():
        return
    event = LibraryEvent.objects.create(kind=kind, collection_id=entry.media_list_id)
    event.works.add(entry.work_id)


def accessible_collections(user):
    from .models import MediaList
    condition = models.Q(visibility="public") | models.Q(owner=user)
    if user.is_superuser or user.has_perm("catalog.view_medialist"):
        condition = models.Q()
    return MediaList.objects.filter(condition)


def updates_for(user):
    """Filter before pagination/counts, including every endpoint in old/new values."""
    from .models import LibraryEvent, WorkFollow, CollectionFollow, Work
    work_follow = WorkFollow.objects.filter(
        user=user, work__library_events=models.OuterRef("pk"),
        created_at__lte=models.OuterRef("created_at"),
    )
    collection_follow = CollectionFollow.objects.filter(
        user=user, collection_id=models.OuterRef("collection_id"),
        created_at__lte=models.OuterRef("created_at"),
    )
    inaccessible = Work.objects.filter(library_events=models.OuterRef("pk")).filter(
        ~models.Q(visibility="public") | models.Q(canonical_redirect__isnull=False)
    )
    return LibraryEvent.objects.annotate(
        work_followed=models.Exists(work_follow), collection_followed=models.Exists(collection_follow),
        inaccessible=models.Exists(inaccessible),
    ).filter(inaccessible=False).filter(
        models.Q(collection__isnull=True, work_followed=True, kind__startswith="relationship_") |
        models.Q(collection__visibility="public", collection_followed=True,
                 created_at__gte=models.F("collection__public_since"))
    ).select_related("collection").prefetch_related(models.Prefetch(
        "works", queryset=Work.objects.select_related("work_type").annotate(
            is_followed=models.Exists(WorkFollow.objects.filter(user=user, work_id=models.OuterRef("pk"))),
        ),
    )).order_by("-created_at", "-pk")
