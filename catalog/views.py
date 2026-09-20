from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from .models import Work, WorkRelationship, WorkType


def public_works():
    return Work.objects.filter(visibility=Work.Visibility.PUBLIC)


def health(request):
    return HttpResponse("ok", content_type="text/plain")


def home(request):
    featured = public_works().select_related("work_type").prefetch_related("credits__agent")[:4]
    return render(request, "catalog/home.html", {"featured": featured})


def discover(request):
    query = request.GET.get("q", "").strip()
    media_type = request.GET.get("type", "").strip()
    works = public_works().select_related("work_type").prefetch_related("credits__agent").annotate(
        connection_count=Count("outgoing_relationships", filter=Q(outgoing_relationships__review_status="accepted"), distinct=True)
        + Count("incoming_relationships", filter=Q(incoming_relationships__review_status="accepted"), distinct=True)
    )
    if query:
        works = works.filter(title__icontains=query)
    if media_type:
        works = works.filter(work_type_id=media_type)
    context = {"works": works, "query": query, "selected_type": media_type, "work_types": WorkType.objects.order_by("label")}
    template = "catalog/_results.html" if request.headers.get("HX-Request") == "true" else "catalog/discover.html"
    return render(request, template, context)


def work_detail(request, pk, slug):
    accepted = WorkRelationship.objects.filter(review_status="accepted").select_related(
        "from_work__work_type", "to_work__work_type", "relationship_type", "source"
    )
    work = get_object_or_404(
        public_works().select_related("work_type").prefetch_related(
            "credits__agent", "versions__releases", "source_links__source",
            Prefetch("outgoing_relationships", queryset=accepted), Prefetch("incoming_relationships", queryset=accepted),
        ), pk=pk,
    )
    return render(request, "catalog/work_detail.html", {"work": work})
