from django.db.models import Q
from django.db.models.signals import pre_delete, post_delete
from django.dispatch import receiver

from .library import record_membership, record_relationship_change, relationship_snapshot
from .models import MediaListEntry, WorkRelationship, Work, LibraryEvent


@receiver(pre_delete, sender=MediaListEntry)
def entry_removed(sender, instance, **kwargs):
    # Django's deletion collector runs these inside its deletion transaction.
    record_membership(instance, "collection_removed")


@receiver(pre_delete, sender=WorkRelationship)
def relationship_removed(sender, instance, **kwargs):
    record_relationship_change(None if instance.pending_publication else relationship_snapshot(instance), None)


@receiver(post_delete, sender=Work)
def remove_events_with_deleted_endpoint(sender, instance, **kwargs):
    # Never retain a partial event whose before/after references a deleted object.
    LibraryEvent.objects.filter(
        Q(before__from=instance.pk) | Q(before__to=instance.pk) |
        Q(after__from=instance.pk) | Q(after__to=instance.pk) | Q(works__isnull=True)
    ).delete()
