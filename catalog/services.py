from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction

from .library import suppress_updates

from .models import (
    ContributionProposal,
    ContributionRevision,
    Credit,
    ExternalIdentifier,
    FeaturedWork,
    ImportItem,
    ImportRelationshipProposal,
    MediaListEntry,
    SourceRecord,
    Version,
    Work,
    WorkRedirect,
    WorkRelationship,
    WorkSource,
)


def _require_merge_permission(actor):
    if not actor or not actor.is_active or not actor.is_staff or not actor.has_perm("catalog.merge_work"):
        raise PermissionDenied("Explicit work merge permission is required.")


def _move_unique_rows(model, source, canonical, lookup_fields):
    """Move rows whose work uniqueness may collide, retaining canonical rows."""
    for row in model.objects.select_for_update().filter(work=source).order_by("pk"):
        lookup = {field: getattr(row, field) for field in lookup_fields}
        if model.objects.filter(work=canonical, **lookup).exists():
            row.delete()
        else:
            row.work = canonical
            row.save(update_fields=("work",))


def _move_versions(source, canonical):
    for version in Version.objects.select_for_update().filter(work=source).order_by("pk"):
        existing = Version.objects.select_for_update().filter(
            work=canonical, label=version.label
        ).first()
        if existing:
            # Releases have no per-version uniqueness constraint, so no release
            # data needs to be discarded when equivalent version labels collide.
            version.releases.update(version=existing)
            version.delete()
        else:
            version.work = canonical
            version.save(update_fields=("work",))


def _move_relationships(source, canonical):
    relationships = WorkRelationship.objects.select_for_update().filter(
        models.Q(from_work=source) | models.Q(to_work=source)
    ).order_by("pk")
    for relationship in relationships:
        from_id = canonical.pk if relationship.from_work_id == source.pk else relationship.from_work_id
        to_id = canonical.pk if relationship.to_work_id == source.pk else relationship.to_work_id
        if from_id == to_id:
            relationship.delete()
            continue
        duplicate = WorkRelationship.objects.filter(
            from_work_id=from_id,
            to_work_id=to_id,
            relationship_type_id=relationship.relationship_type_id,
        ).exclude(pk=relationship.pk)
        if duplicate.exists():
            relationship.delete()
            continue
        relationship.from_work_id = from_id
        relationship.to_work_id = to_id
        relationship.save(update_fields=("from_work", "to_work"))


def _move_list_entries(source, canonical):
    for entry in MediaListEntry.objects.select_for_update().filter(work=source).order_by("pk"):
        existing = MediaListEntry.objects.select_for_update().filter(
            media_list=entry.media_list, work=canonical
        ).first()
        if existing:
            # Keep the canonical entry's ordering, while preserving distinct notes.
            if entry.commentary and entry.commentary not in existing.commentary:
                existing.commentary = "\n\n".join(filter(None, (existing.commentary, entry.commentary)))
                existing.save(update_fields=("commentary",))
            entry.delete()
        else:
            entry.work = canonical
            entry.save(update_fields=("work",))


@suppress_updates()
@transaction.atomic
def merge_works(*, source, canonical, actor):
    """Merge ``source`` into ``canonical`` and leave a durable URL redirect."""
    _require_merge_permission(actor)
    if source.pk is None or canonical.pk is None:
        raise ValidationError("Both works must be saved before merging.")
    if source.pk == canonical.pk:
        raise ValidationError("A work cannot be merged into itself.")

    locked = {
        work.pk: work
        for work in Work.objects.select_for_update().filter(
            pk__in=(source.pk, canonical.pk)
        ).order_by("pk")
    }
    if len(locked) != 2:
        raise ValidationError("Both works must still exist.")
    source, canonical = locked[source.pk], locked[canonical.pk]
    if WorkRedirect.objects.filter(old_work=source).exists():
        raise ValidationError("The source work has already been merged.")
    if WorkRedirect.objects.filter(old_work=canonical).exists():
        raise ValidationError("Merge into the final canonical work, not another redirect.")

    from .models import SavedWork, WorkFollow
    _move_unique_rows(SavedWork, source, canonical, ("user",))
    _move_unique_rows(WorkFollow, source, canonical, ("user",))
    _move_unique_rows(Credit, source, canonical, ("agent", "role"))
    _move_versions(source, canonical)
    _move_unique_rows(ExternalIdentifier, source, canonical, ("scheme", "value"))
    _move_unique_rows(WorkSource, source, canonical, ("source",))
    _move_relationships(source, canonical)
    _move_list_entries(source, canonical)

    # Merged evidence is retained as history, never silently attached to the canonical value.
    from .models import FieldEvidence
    FieldEvidence.objects.filter(work=source).update(work=canonical, current=False)
    SourceRecord.objects.filter(matched_work=source).update(matched_work=canonical)
    ImportItem.objects.filter(work=source).update(work=canonical)
    ContributionProposal.objects.filter(work=source).update(work=canonical)
    ContributionProposal.objects.filter(related_work=source).update(related_work=canonical)
    ContributionRevision.objects.filter(work=source).update(work=canonical)
    ImportRelationshipProposal.objects.filter(from_work=source).update(from_work=canonical)
    ImportRelationshipProposal.objects.filter(to_work=source).update(to_work=canonical)

    source_feature = FeaturedWork.objects.select_for_update().filter(work=source).first()
    if source_feature:
        if FeaturedWork.objects.select_for_update().filter(work=canonical).exists():
            source_feature.delete()
        else:
            source_feature.work = canonical
            source_feature.save(update_fields=("work",))

    # Flatten redirects from earlier merges so URL resolution is one hop.
    WorkRedirect.objects.filter(canonical_work=source).update(canonical_work=canonical)
    return WorkRedirect.objects.create(
        old_work=source, canonical_work=canonical, merged_by=actor
    )
