from django import template
from django.db.models import Q

from catalog.models import (
    ImportRelationshipProposal,
    ImportRun,
    MediaList,
    SourceRecord,
    Work,
    WorkRelationship,
)

register = template.Library()


@register.inclusion_tag("admin/_oma_summary.html")
def oma_admin_summary():
    latest_run = ImportRun.objects.select_related("source").order_by("-id").first()
    golden_edges = Q(from_work__depth="editorial", from_work__is_demo=False) | Q(to_work__depth="editorial", to_work__is_demo=False)
    return {
        "works_total": Work.objects.count(),
        "works_public": Work.objects.filter(visibility=Work.Visibility.PUBLIC).count(),
        "works_draft": Work.objects.filter(visibility=Work.Visibility.DRAFT).count(),
        "works_editorial": Work.objects.filter(depth="editorial", is_demo=False).count(),
        "works_adaptations": Work.objects.filter(visibility=Work.Visibility.PUBLIC, is_demo=False, depth="index").count(),
        "works_undated": Work.objects.filter(visibility=Work.Visibility.PUBLIC, is_demo=False, first_publication_year__isnull=True).count(),
        "works_with_image": Work.objects.exclude(image_url="").count(),
        "works_without_image": Work.objects.filter(image_url="").count(),
        "relationships_accepted": WorkRelationship.objects.filter(review_status="accepted").count(),
        "relationships_golden": WorkRelationship.objects.filter(golden_edges, review_status="accepted").count(),
        "proposals_pending": ImportRelationshipProposal.objects.filter(status="pending").count(),
        "proposals_golden_pending": ImportRelationshipProposal.objects.filter(golden_edges, status="pending").count(),
        "proposals_undated_pending": ImportRelationshipProposal.objects.filter(
            Q(from_work__first_publication_year__isnull=True)
            | Q(to_work__first_publication_year__isnull=True),
            status="pending",
        ).count(),
        "proposals_approved": ImportRelationshipProposal.objects.filter(status="approved").count(),
        "source_records": SourceRecord.objects.count(),
        "latest_run": latest_run,
        "golden_list": MediaList.objects.filter(
            title="Golden 20", visibility=MediaList.Visibility.PUBLIC
        ).first(),
    }
