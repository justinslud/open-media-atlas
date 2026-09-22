from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from .models import FeaturedWork, Work, WorkRelationship, WorkType


def public_works():
    """Return the public catalog, preferring real records over demo fixtures."""
    works = Work.objects.filter(visibility=Work.Visibility.PUBLIC)
    if works.filter(is_demo=False).exists():
        works = works.filter(is_demo=False)
    return works


def health(request):
    return HttpResponse("ok", content_type="text/plain")


def home(request):
    public = public_works()
    featured = (
        FeaturedWork.objects.filter(work__in=public)
        .select_related("work__work_type")
        .prefetch_related("work__credits__agent")
        .order_by("position", "id")[:6]
    )

    # A useful fallback keeps a newly imported catalog from producing an empty
    # homepage, without pretending that the fallback is an editorial choice.
    fallback_works = []
    if not featured:
        fallback_works = list(
            public.select_related("work_type").prefetch_related("credits__agent")[:6]
        )

    relationships = (
        WorkRelationship.objects.filter(
            review_status="accepted", from_work__in=public, to_work__in=public
        )
        .select_related(
            "from_work__work_type", "to_work__work_type", "relationship_type"
        )
        .prefetch_related("from_work__credits__agent", "to_work__credits__agent")
        .order_by("id")[:3]
    )
    return render(
        request,
        "catalog/home.html",
        {
            "featured_selections": featured,
            "fallback_works": fallback_works,
            "featured_is_fallback": bool(fallback_works),
            "relationships": relationships,
        },
    )


def discover(request):
    query = request.GET.get("q", "").strip()
    media_type = request.GET.get("type", "").strip()
    public = public_works()
    works = (
        public.select_related("work_type")
        .prefetch_related("credits__agent")
        .annotate(
            connection_count=Count(
                "outgoing_relationships",
                filter=Q(
                    outgoing_relationships__review_status="accepted",
                    outgoing_relationships__to_work__in=public,
                ),
                distinct=True,
            )
            + Count(
                "incoming_relationships",
                filter=Q(
                    incoming_relationships__review_status="accepted",
                    incoming_relationships__from_work__in=public,
                ),
                distinct=True,
            )
        )
    )
    if query:
        works = works.filter(
            Q(title__icontains=query)
            | Q(credits__agent__name__icontains=query)
        ).distinct()
    if media_type:
        works = works.filter(work_type_id=media_type)
    context = {
        "works": works,
        "query": query,
        "selected_type": media_type,
        "work_types": WorkType.objects.order_by("label"),
    }
    template = (
        "catalog/_results.html"
        if request.headers.get("HX-Request") == "true"
        else "catalog/discover.html"
    )
    return render(request, template, context)


def work_detail(request, pk, slug):
    public = public_works()
    accepted_outgoing = WorkRelationship.objects.filter(
        review_status="accepted", to_work__in=public
    ).select_related("to_work__work_type", "relationship_type", "source")
    accepted_incoming = WorkRelationship.objects.filter(
        review_status="accepted", from_work__in=public
    ).select_related("from_work__work_type", "relationship_type", "source")
    work = get_object_or_404(
        public.select_related("work_type").prefetch_related(
            "credits__agent",
            "versions__releases",
            "source_links__source",
            "identifiers",
            Prefetch("outgoing_relationships", queryset=accepted_outgoing),
            Prefetch("incoming_relationships", queryset=accepted_incoming),
        ),
        pk=pk,
    )

    relationship_groups = {
        "adaptations": [],
        "recordings": [],
        "commentary": [],
        "other": [],
    }
    for relationship in work.outgoing_relationships.all():
        relationship.display_label = relationship.relationship_type.label
        relationship.related_work = relationship.to_work
        category = relationship.relationship_type.category
        if category == "derivation":
            category = "adaptations"
        key = category if category in relationship_groups else "other"
        relationship_groups[key].append(relationship)
    for relationship in work.incoming_relationships.all():
        relationship.display_label = relationship.relationship_type.inverse_label
        relationship.related_work = relationship.from_work
        category = relationship.relationship_type.category
        if category == "derivation":
            category = "adaptations"
        key = category if category in relationship_groups else "other"
        relationship_groups[key].append(relationship)

    # Existing URLs are the only availability data in this milestone. Present
    # them as source/catalog links rather than making an unsupported access claim.
    primary_link = next(
        (link.source for link in work.source_links.all() if link.source.url), None
    )
    if primary_link is None:
        open_library_id = next(
            (item.value for item in work.identifiers.all() if item.scheme == "ol_work"),
            None,
        )
        if open_library_id:
            primary_link = {
                "url": f"https://openlibrary.org/works/{open_library_id}",
                "title": "View at Open Library",
            }

    has_relationships = any(relationship_groups.values())
    return render(
        request,
        "catalog/work_detail.html",
        {
            "work": work,
            "relationship_groups": relationship_groups,
            "has_relationships": has_relationships,
            "primary_link": primary_link,
        },
    )
