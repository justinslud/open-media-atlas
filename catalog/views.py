from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.models import EmailVerification
from .forms import EntryCommentaryForm, MediaListForm
from .models import FeaturedWork, MediaList, MediaListEntry, Work, WorkRelationship, WorkType


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
            "owned_lists": MediaList.objects.filter(owner=request.user) if request.user.is_authenticated else (),
        },
    )


def _can_publish(user):
    return EmailVerification.objects.filter(user=user, verified_at__isnull=False).exists()


def _can_view_private(user):
    return user.is_authenticated and (user.is_superuser or user.has_perm("catalog.view_medialist"))


def _owned_list(request, pk):
    return get_object_or_404(MediaList, pk=pk, owner=request.user)


@require_GET
def public_lists(request):
    lists = MediaList.objects.filter(visibility=MediaList.Visibility.PUBLIC).select_related("owner").annotate(
        item_count=Count("entries", filter=Q(entries__work__visibility=Work.Visibility.PUBLIC))
    ).order_by("-updated_at", "-id")
    return render(request, "catalog/public_lists.html", {"page_obj": Paginator(lists, 12).get_page(request.GET.get("page"))})


def list_detail(request, pk, slug):
    media_list = get_object_or_404(MediaList.objects.select_related("owner"), pk=pk)
    is_owner = request.user.is_authenticated and media_list.owner_id == request.user.id
    if media_list.visibility != MediaList.Visibility.PUBLIC and not (is_owner or _can_view_private(request.user)):
        raise Http404
    entries = media_list.entries.select_related("work__work_type").prefetch_related("work__credits__agent")
    return render(request, "catalog/list_detail.html", {"media_list": media_list, "entries": entries, "is_owner": is_owner})


@login_required
def my_lists(request):
    lists = MediaList.objects.filter(owner=request.user).annotate(item_count=Count("entries"))
    return render(request, "catalog/my_lists.html", {"lists": lists})


@login_required
@require_http_methods(["GET", "POST"])
def list_create(request):
    form = MediaListForm(request.POST or None, can_publish=_can_publish(request.user))
    if request.method == "POST" and form.is_valid():
        media_list = form.save(commit=False)
        media_list.owner = request.user
        media_list.save()
        messages.success(request, "List created.")
        return redirect("list-edit", pk=media_list.pk)
    return render(request, "catalog/list_form.html", {"form": form, "heading": "Create a list"})


@login_required
@require_http_methods(["GET", "POST"])
def list_edit(request, pk):
    media_list = _owned_list(request, pk)
    form = MediaListForm(request.POST or None, instance=media_list, can_publish=_can_publish(request.user))
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "List updated.")
        return redirect("list-edit", pk=pk)
    return render(request, "catalog/list_form.html", {"form": form, "heading": "Edit list", "media_list": media_list})


@login_required
@require_http_methods(["GET", "POST"])
def list_delete(request, pk):
    media_list = _owned_list(request, pk)
    if request.method == "POST":
        media_list.delete()
        messages.success(request, "List deleted.")
        return redirect("my-lists")
    return render(request, "catalog/list_confirm_delete.html", {"media_list": media_list})


@login_required
@require_GET
def list_work_search(request, pk):
    media_list = _owned_list(request, pk)
    query = request.GET.get("q", "").strip()[:200]
    works = public_works().select_related("work_type").prefetch_related("credits__agent")
    if query:
        works = works.filter(Q(title__icontains=query) | Q(credits__agent__name__icontains=query)).distinct()[:20]
    else:
        works = works.none()
    return render(request, "catalog/_list_search_results.html", {"media_list": media_list, "works": works, "query": query})


@login_required
@require_POST
def list_add_work(request, pk, work_pk):
    media_list = _owned_list(request, pk)
    work = get_object_or_404(public_works(), pk=work_pk)
    if media_list.entries.filter(work=work).exists():
        messages.info(request, "That work is already in this list.")
    else:
        position = (media_list.entries.aggregate(Max("position"))["position__max"] or 0) + 1
        MediaListEntry.objects.create(media_list=media_list, work=work, position=position)
        messages.success(request, f"Added {work.title}.")
    return redirect("list-edit", pk=pk)


@login_required
@require_http_methods(["GET", "POST"])
def list_entry_edit(request, pk, entry_pk):
    media_list = _owned_list(request, pk)
    entry = get_object_or_404(MediaListEntry, pk=entry_pk, media_list=media_list)
    form = EntryCommentaryForm(request.POST or None, instance=entry)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Commentary updated.")
        return redirect("list-edit", pk=pk)
    return render(request, "catalog/entry_form.html", {"form": form, "entry": entry, "media_list": media_list})


@login_required
@require_POST
def list_entry_remove(request, pk, entry_pk):
    media_list = _owned_list(request, pk)
    entry = get_object_or_404(MediaListEntry, pk=entry_pk, media_list=media_list)
    entry.delete()
    _normalize_positions(media_list)
    messages.success(request, "Entry removed.")
    return redirect("list-edit", pk=pk)


def _normalize_positions(media_list):
    with transaction.atomic():
        entries = list(media_list.entries.order_by("position", "id"))
        offset = len(entries) + 1
        for entry in entries:
            MediaListEntry.objects.filter(pk=entry.pk).update(position=entry.position + offset)
        for position, entry in enumerate(entries, 1):
            MediaListEntry.objects.filter(pk=entry.pk).update(position=position)


@login_required
@require_POST
def list_entry_move(request, pk, entry_pk, direction):
    media_list = _owned_list(request, pk)
    if direction not in ("up", "down"):
        raise Http404
    get_object_or_404(MediaListEntry, pk=entry_pk, media_list=media_list)
    entries = list(media_list.entries.order_by("position", "id"))
    index = next((i for i, entry in enumerate(entries) if entry.pk == entry_pk), None)
    target = index - 1 if direction == "up" else index + 1
    if index is not None and 0 <= target < len(entries):
        entries[index], entries[target] = entries[target], entries[index]
        with transaction.atomic():
            offset = len(entries) + 1
            for entry in entries:
                MediaListEntry.objects.filter(pk=entry.pk).update(position=entry.position + offset)
            for position, entry in enumerate(entries, 1):
                MediaListEntry.objects.filter(pk=entry.pk).update(position=position)
    return redirect("list-edit", pk=pk)


@login_required
@require_http_methods(["GET", "POST"])
def add_to_list(request, work_pk):
    work = get_object_or_404(public_works(), pk=work_pk)
    lists = MediaList.objects.filter(owner=request.user)
    if request.method == "POST":
        list_id = request.POST.get("list_id")
        if list_id:
            media_list = get_object_or_404(lists, pk=list_id)
        else:
            title = request.POST.get("title", "").strip()
            if not title or len(title) > 120:
                return render(request, "catalog/add_to_list.html", {"work": work, "lists": lists, "error": "Enter a list title of 120 characters or fewer."})
            media_list = MediaList.objects.create(owner=request.user, title=title)
        if media_list.entries.filter(work=work).exists():
            messages.info(request, "That work is already in this list.")
        else:
            position = (media_list.entries.aggregate(Max("position"))["position__max"] or 0) + 1
            MediaListEntry.objects.create(media_list=media_list, work=work, position=position)
            messages.success(request, f"Added {work.title} to {media_list.title}.")
        return redirect("list-edit", pk=media_list.pk)
    return render(request, "catalog/add_to_list.html", {"work": work, "lists": lists})


def _verified_submission_allowed(request):
    return EmailVerification.objects.filter(user=request.user, verified_at__isnull=False).exists()


@login_required
@require_http_methods(["GET", "POST"])
def suggest_correction(request, pk):
    from accounts.rate_limits import client_key, is_limited
    from .forms import CorrectionProposalForm
    from .models import ContributionProposal
    work = get_object_or_404(public_works(), pk=pk)
    form = CorrectionProposalForm(request.POST or None)
    verification_required = not _verified_submission_allowed(request)
    if request.method == "POST" and form.is_valid():
        if verification_required:
            form.add_error(None, "Verify your email address before submitting. Your entries remain below.")
        elif is_limited("contribution", client_key(request, str(request.user.pk))):
            return render(request, "accounts/rate_limited.html", status=429)
        else:
            field = form.cleaned_data["field_name"]
            ContributionProposal.objects.create(kind="correction", submitted_by=request.user, work=work,
                field_name=field, value_at_submission=str(getattr(work, field)),
                proposed_value=form.cleaned_data["proposed_value"], work_updated_at=work.updated_at,
                explanation=form.cleaned_data["explanation"], source_url=form.cleaned_data["source_url"])
            messages.success(request, "Correction submitted for editorial review.")
            return redirect("my-contributions")
    return render(request, "catalog/contribution_form.html", {"form": form, "work": work,
        "heading": "Suggest a correction", "verification_required": verification_required})


@login_required
@require_http_methods(["GET", "POST"])
def suggest_relationship(request, pk):
    from accounts.rate_limits import client_key, is_limited
    from .forms import RelationshipProposalForm
    from .models import ContributionProposal
    work = get_object_or_404(public_works(), pk=pk)
    form = RelationshipProposalForm(request.POST or None, source_work=work)
    verification_required = not _verified_submission_allowed(request)
    direction = None
    if form.is_bound and form.is_valid():
        target, relationship_type = form.cleaned_data["related_work"], form.cleaned_data["relationship_type"]
        direction = f"{work.title} — {relationship_type.label} — {target.title}"
        if request.method == "POST":
            if verification_required:
                form.add_error(None, "Verify your email address before submitting. Your entries remain below.")
            elif is_limited("contribution", client_key(request, str(request.user.pk))):
                return render(request, "accounts/rate_limited.html", status=429)
            else:
                ContributionProposal.objects.create(kind="relationship", submitted_by=request.user, work=work,
                    related_work=target, relationship_type=relationship_type, work_updated_at=work.updated_at,
                    related_work_updated_at=target.updated_at, explanation=form.cleaned_data["explanation"],
                    source_url=form.cleaned_data["source_url"])
                messages.success(request, "Relationship submitted for editorial review.")
                return redirect("my-contributions")
    return render(request, "catalog/contribution_form.html", {"form": form, "work": work,
        "heading": "Suggest a relationship", "direction": direction, "verification_required": verification_required})


@login_required
@require_GET
def my_contributions(request):
    from .models import ContributionProposal
    proposals = ContributionProposal.objects.filter(submitted_by=request.user).select_related(
        "work", "related_work", "relationship_type", "reviewer")
    return render(request, "catalog/my_contributions.html", {"proposals": proposals})
