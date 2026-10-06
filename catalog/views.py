from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.models import EmailVerification
from .discovery import DISCOVERY_ORDER, catalog_queryset, filter_public_type, search
from .forms import EntryCommentaryForm, MediaListForm
from .models import (
    FeaturedWork, MediaList, MediaListEntry, Work, WorkRedirect, WorkRelationship,
    WorkTermAssignment, WorkType,
)


DISCOVER_PAGE_SIZE = 30


def _open_library_url(value, kind):
    """Return a canonical Open Library URL for a supported structured key."""
    if not value:
        return None
    value = str(value).strip().split("?", 1)[0].rstrip("/")
    prefix, suffix = ("works", "W") if kind == "work" else ("books", "M")
    marker = f"/{prefix}/"
    if marker in value:
        value = value.rsplit(marker, 1)[1]
    elif value.startswith("/") or "/" in value:
        return None
    if not value.startswith("OL") or not value.endswith(suffix) or not value[2:-1].isdigit():
        return None
    return f"https://openlibrary.org/{prefix}/{value}"


def public_works():
    """Return the public catalog, preferring real records over demo fixtures."""
    works = Work.objects.filter(
        visibility=Work.Visibility.PUBLIC, canonical_redirect__isnull=True
    )
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
        .prefetch_related("work__credits__agent", "work__source_records")
        .order_by("position", "id")[:6]
    )

    # A useful fallback keeps a newly imported catalog from producing an empty
    # homepage, without pretending that the fallback is an editorial choice.
    fallback_works = []
    if not featured:
        fallback_works = list(
            catalog_queryset(public).order_by(*DISCOVERY_ORDER)[:6]
        )

    relationships = (
        WorkRelationship.objects.filter(
            review_status="accepted", from_work__in=public, to_work__in=public
        )
        .select_related(
            "from_work__work_type", "to_work__work_type", "relationship_type"
        )
        .prefetch_related("from_work__credits__agent", "to_work__credits__agent", "from_work__source_records", "to_work__source_records")
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
    media_type = {"creative-work": "unclassified", "unknown": "unclassified", "literary-work": "written-work"}.get(media_type, media_type)
    creator = request.GET.get("creator", "").strip()[:200]
    year_from = request.GET.get("year_from", "").strip()
    year_to = request.GET.get("year_to", "").strip()
    relationship = request.GET.get("relationship", "").strip()
    sort = request.GET.get("sort", "auto").strip()
    public = public_works()
    works = catalog_queryset(public)
    if creator:
        works = works.filter(credits__agent__name__icontains=creator).distinct()
    if year_from.isdigit():
        works = works.filter(first_publication_year__gte=int(year_from))
    if year_to.isdigit():
        works = works.filter(first_publication_year__lte=int(year_to))
    if relationship == "has_adaptations":
        # Relationships are stored derived work -> source work.
        works = works.filter(
            incoming_relationships__review_status="accepted",
            incoming_relationships__relationship_type__category="derivation",
            incoming_relationships__from_work__in=public,
        ).distinct()
    elif relationship == "is_adaptation":
        works = works.filter(
            outgoing_relationships__review_status="accepted",
            outgoing_relationships__relationship_type__category="derivation",
            outgoing_relationships__to_work__in=public,
        ).distinct()
    if media_type:
        works = filter_public_type(works, media_type)
    if query:
        works = search(works, query)
    orderings = {
        "title": ("title", "first_publication_year", "id"),
        "newest": ("-first_publication_year", "title", "id"),
        "oldest": ("first_publication_year", "title", "id"),
    }
    if sort not in {"auto", *orderings}:
        sort = "auto"
    ordering = orderings.get(sort, (("relevance", "relevance_distance") + DISCOVERY_ORDER if query else DISCOVERY_ORDER))
    works = works.order_by(*ordering)
    page_obj = Paginator(works, DISCOVER_PAGE_SIZE).get_page(request.GET.get("page"))
    preserved = request.GET.copy()
    preserved.pop("page", None)
    context = {
        "works": page_obj.object_list,
        "page_obj": page_obj,
        "result_count": page_obj.paginator.count,
        "querystring": preserved.urlencode(),
        "query": query,
        "selected_type": media_type,
        "creator": creator,
        "year_from": year_from,
        "year_to": year_to,
        "selected_relationship": relationship,
        "selected_sort": sort,
        "has_filters": any((query, media_type, creator, year_from, year_to, relationship)),
        "work_types": [{"pk": "book", "label": "Books (including novels)"},
                       {"pk": "unclassified", "label": "Unclassified works"},
                       {"pk": "written-work", "label": "Written works (type unspecified)"}] + [
            {"pk": kind.pk, "label": "Written works (type unspecified)" if kind.pk in {"literary-work", "written-work"} else kind.label}
            for kind in WorkType.objects.exclude(pk__in=("book", "creative-work", "unknown", "literary-work", "written-work")).order_by("label")
        ],
    }
    template = (
        "catalog/_results.html"
        if request.headers.get("HX-Request") == "true"
        else "catalog/discover.html"
    )
    return render(request, template, context)


def work_detail(request, pk, slug):
    canonical = WorkRedirect.objects.select_related("canonical_work").filter(old_work_id=pk).first()
    if canonical:
        return redirect(canonical.canonical_work.get_absolute_url(), permanent=True)
    public = public_works()
    accepted_outgoing = WorkRelationship.objects.filter(
        review_status="accepted", to_work__in=public
    ).select_related("to_work__work_type", "relationship_type", "source").prefetch_related("to_work__credits__agent", "to_work__source_records")
    accepted_incoming = WorkRelationship.objects.filter(
        review_status="accepted", from_work__in=public
    ).select_related("from_work__work_type", "relationship_type", "source").prefetch_related("from_work__credits__agent", "from_work__source_records")
    work = get_object_or_404(
        public.select_related("work_type").prefetch_related(
            "credits__agent",
            "source_records__source",
            "source_records__work_state",
            "field_evidence__source",
            "contribution_revisions",
            "versions__releases",
            "source_links__source",
            "identifiers",
            Prefetch("outgoing_relationships", queryset=accepted_outgoing),
            Prefetch("incoming_relationships", queryset=accepted_incoming),
            Prefetch(
                "term_assignments",
                queryset=WorkTermAssignment.objects.filter(
                    review_state=WorkTermAssignment.ReviewState.ACCEPTED
                ).select_related("term", "source"),
                to_attr="accepted_term_assignments",
            ),
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
    open_library_url = next(
        (_open_library_url(item.value, "work") for item in work.identifiers.all()
         if item.scheme == "ol_work" and _open_library_url(item.value, "work")),
        None,
    )
    wikidata_url = next(
        (f"https://www.wikidata.org/wiki/{item.value}" for item in work.identifiers.all()
         if item.scheme == "wikidata" and item.value.startswith("Q") and item.value[1:].isdigit()), None)
    primary_link = ({"url": open_library_url, "title": "View on Open Library"} if open_library_url else
                    ({"url": wikidata_url, "title": "View on Wikidata"} if wikidata_url else next(
        (link.source for link in work.source_links.all()
         if link.source.url and "openlibrary.org" not in link.source.url.lower()), None
    )))
    for version in work.versions.all():
        for release in version.releases.all():
            release.open_library_url = _open_library_url(release.openlibrary_key, "edition")

    from .provenance import work_provenance, relationship_provenance, rights_provenance
    provenance = work_provenance(work)
    for relationships in relationship_groups.values():
        for rel in relationships:
            rel.provenance = relationship_provenance(rel)
            rel.rights_provenance = rights_provenance(rel) if rel.authorization_statement else None
    has_relationships = any(relationship_groups.values())
    return render(
        request,
        "catalog/work_detail.html",
        {
            "work": work,
            "relationship_groups": relationship_groups,
            "provenance": provenance,
            "has_relationships": has_relationships,
            "primary_link": primary_link,
            "owned_lists": MediaList.objects.filter(owner=request.user) if request.user.is_authenticated else (),
            "open_library_url": open_library_url,
            "wikidata_url": wikidata_url,
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
    entries = media_list.entries.select_related("work__work_type").prefetch_related("work__credits__agent", "work__source_records")
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
    lists = MediaList.objects.filter(owner=request.user).annotate(
        contains_work=Count("entries", filter=Q(entries__work=work))
    )
    if request.method == "POST":
        list_id = request.POST.get("list_id")
        if list_id:
            media_list = get_object_or_404(lists, pk=list_id)
        else:
            title = request.POST.get("title", "").strip()
            if not title or len(title) > 120:
                return render(request, "catalog/add_to_list.html", {"work": work, "lists": lists, "error": "Enter a list title of 120 characters or fewer."})
            media_list = MediaList.objects.create(owner=request.user, title=title)
        with transaction.atomic():
            if media_list.entries.select_for_update().filter(work=work).exists():
                messages.info(request, f"{work.title} is already in {media_list.title}.")
            else:
                position = (media_list.entries.aggregate(Max("position"))["position__max"] or 0) + 1
                MediaListEntry.objects.create(media_list=media_list, work=work, position=position)
                messages.success(request, f"Added {work.title} to {media_list.title}.")
        return redirect(media_list.get_absolute_url())
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
    from .models import WorkRelationship, WorkType
    relationship_id = request.POST.get("target_relationship") if request.method == "POST" else request.GET.get("relationship")
    relationship = None
    if relationship_id:
        relationship = get_object_or_404(WorkRelationship.objects.select_related("from_work", "to_work"),
            pk=relationship_id, from_work=work, review_status="accepted", to_work__in=public_works())
    initial_field = request.GET.get("field", "relationship_type" if relationship else "title")
    allowed = {name for name, _ in CorrectionProposalForm.FIELD_CHOICES}
    if initial_field not in allowed:
        initial_field = "title"
    form = CorrectionProposalForm(request.POST or None, initial={"field_name": initial_field})
    relationship_fields = {"scope_note", "relationship_type", "authorization_statement"}
    form.fields["field_name"].choices = [choice for choice in form.FIELD_CHOICES
        if (choice[0] in relationship_fields) == bool(relationship)]
    selected_field = request.POST.get("field_name", initial_field)
    current_value = (ContributionProposal(work=work, field_name=selected_field, kind="correction", target_relationship=relationship).current_value
                     if selected_field in {choice[0] for choice in form.fields["field_name"].choices} else "")
    form.fields["proposed_value"].help_text = "Propose the replacement value; it will remain pending until reviewed."
    if selected_field in {"work_type", "relationship_type"}:
        from .models import RelationshipType
        types = WorkType if selected_field == "work_type" else RelationshipType
        form.fields["proposed_value"].help_text = "Use a catalog code: " + ", ".join(types.objects.values_list("code", flat=True))
    verification_required = not _verified_submission_allowed(request)
    if request.method == "POST" and form.is_valid():
        if verification_required:
            form.add_error(None, "Verify your email address before submitting. Your entries remain below.")
        elif is_limited("contribution", client_key(request, str(request.user.pk))):
            return render(request, "accounts/rate_limited.html", status=429)
        else:
            field = form.cleaned_data["field_name"]
            ContributionProposal.objects.create(kind="correction", submitted_by=request.user, work=work,
                field_name=field, target_relationship=relationship, value_at_submission=current_value,
                proposed_value=form.cleaned_data["proposed_value"], work_updated_at=work.updated_at,
                explanation=form.cleaned_data["explanation"], source_url=form.cleaned_data["source_url"])
            messages.success(request, "Correction submitted for editorial review.")
            return redirect("my-contributions")
    return render(request, "catalog/contribution_form.html", {"form": form, "work": work,
        "heading": "Suggest a correction", "verification_required": verification_required,
        "current_value": current_value, "target_relationship": relationship})


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
        "heading": "Suggest a relationship", "direction": direction, "verification_required": verification_required,
        "relationship_form": True})


@login_required
@require_GET
def relationship_work_search(request, pk):
    """Return a small, selectable set of public relationship targets."""
    source_work = get_object_or_404(public_works(), pk=pk)
    query = request.GET.get("work_q", "").strip()[:200]
    works = public_works().exclude(pk=source_work.pk).select_related("work_type")
    if query:
        lookup = Q(title__icontains=query)
        if query.isdigit():
            lookup |= Q(pk=int(query))
        works = works.filter(lookup).order_by("title", "id")[:20]
    else:
        works = works.none()
    return render(request, "catalog/_relationship_work_results.html", {
        "works": works, "query": query, "selected_id": request.GET.get("related_work", ""),
    })


@login_required
@require_http_methods(["GET", "POST"])
def suggest_term(request, pk):
    from accounts.rate_limits import client_key, is_limited
    from .forms import TermSuggestionForm

    work = get_object_or_404(public_works(), pk=pk)
    form = TermSuggestionForm(request.POST or None, work=work)
    verification_required = not _verified_submission_allowed(request)
    if request.method == "POST" and form.is_valid():
        if verification_required:
            form.add_error(None, "Verify your email address before submitting. Your entries remain below.")
        elif is_limited("contribution", client_key(request, str(request.user.pk))):
            return render(request, "accounts/rate_limited.html", status=429)
        else:
            WorkTermAssignment.objects.create(
                work=work, term=form.cleaned_data["term"], submitted_by=request.user,
                provenance_note=form.cleaned_data["provenance_note"],
                source_url=form.cleaned_data["source_url"],
            )
            messages.success(request, "Term submitted for editorial review.")
            return redirect("my-contributions")
    return render(request, "catalog/contribution_form.html", {
        "form": form, "work": work, "heading": "Suggest a term",
        "verification_required": verification_required,
    })


@login_required
@require_GET
def my_contributions(request):
    from .models import ContributionProposal
    proposals = ContributionProposal.objects.filter(submitted_by=request.user).select_related(
        "work", "related_work", "relationship_type", "reviewer")
    term_suggestions = WorkTermAssignment.objects.filter(
        submitted_by=request.user
    ).select_related("work", "term", "reviewer")
    return render(request, "catalog/my_contributions.html", {
        "proposals": proposals, "term_suggestions": term_suggestions,
    })


@login_required
@require_http_methods(["GET", "POST"])
def resubmit_contribution(request, pk):
    """Let an owner answer a clarification request as a separately audited attempt."""
    from .forms import CorrectionProposalForm, RelationshipProposalForm
    from .models import ContributionProposal

    proposal = get_object_or_404(
        ContributionProposal.objects.select_related("work", "related_work", "relationship_type"),
        pk=pk, submitted_by=request.user,
        status=ContributionProposal.Status.CLARIFICATION_NEEDED,
    )
    if proposal.kind == ContributionProposal.Kind.CORRECTION:
        form_class = CorrectionProposalForm
        form_kwargs = {}
        initial = {"field_name": proposal.field_name, "proposed_value": proposal.proposed_value,
                   "explanation": proposal.explanation, "source_url": proposal.source_url}
    else:
        form_class = RelationshipProposalForm
        form_kwargs = {"source_work": proposal.work}
        initial = {"related_work": proposal.related_work, "relationship_type": proposal.relationship_type,
                   "explanation": proposal.explanation, "source_url": proposal.source_url}
    form = form_class(request.POST or None, initial=initial, **form_kwargs)
    if proposal.kind == ContributionProposal.Kind.CORRECTION:
        # A revision may answer the reviewer, but it must not silently become a
        # proposal about a different catalog field.
        form.fields["field_name"].disabled = True
    verification_required = not _verified_submission_allowed(request)
    if request.method == "POST" and form.is_valid():
        if verification_required:
            form.add_error(None, "Verify your email address before resubmitting. Your entries remain below.")
        else:
            proposal.resubmit(
                contributor=request.user,
                proposed_value=form.cleaned_data.get("proposed_value", ""),
                related_work=form.cleaned_data.get("related_work"),
                relationship_type=form.cleaned_data.get("relationship_type"),
                explanation=form.cleaned_data["explanation"], source_url=form.cleaned_data["source_url"],
            )
            messages.success(request, "Revised proposal submitted for editorial review.")
            return redirect("my-contributions")
    return render(request, "catalog/contribution_form.html", {
        "form": form, "work": proposal.work, "heading": "Revise and resubmit",
        "verification_required": verification_required, "proposal": proposal,
        "target_relationship": proposal.target_relationship,
        "relationship_form": proposal.kind == ContributionProposal.Kind.RELATIONSHIP,
    })
