import json

from django.contrib import admin
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    Agent, Credit, ExternalIdentifier, FeaturedWork, ImportedWorkState,
    ImportItem, ImportRun, ImportRelationshipProposal, Release, RelationshipType, Source, SourceRecord,
    MediaList, MediaListEntry, Term, Version, Work, WorkRedirect, WorkRelationship,
    WorkSource, WorkTermAssignment, WorkType,
)
from .services import merge_works


class CreditInline(admin.TabularInline):
    model = Credit
    extra = 0


class VersionInline(admin.TabularInline):
    model = Version
    extra = 0


class WorkSourceInline(admin.TabularInline):
    model = WorkSource
    extra = 0


class ExternalIdentifierInline(admin.TabularInline):
    model = ExternalIdentifier
    extra = 0
    fields = ("scheme", "value")
    readonly_fields = ("scheme", "value")
    can_delete = False


class HasImageFilter(admin.SimpleListFilter):
    title = "image"
    parameter_name = "has_image"

    def lookups(self, request, model_admin):
        return (("yes", "Has image"), ("no", "No image"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(image_url="")
        if self.value() == "no":
            return queryset.filter(image_url="")
        return queryset


class HasDateFilter(admin.SimpleListFilter):
    title = "date"
    parameter_name = "has_date"

    def lookups(self, request, model_admin):
        return (("yes", "Has year"), ("no", "No year"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(first_publication_year__isnull=False)
        if self.value() == "no":
            return queryset.filter(first_publication_year__isnull=True)
        return queryset


class WikipediaDateFilter(admin.SimpleListFilter):
    title = "Wikipedia infobox date"
    parameter_name = "wikipedia_date"

    def lookups(self, request, model_admin):
        return (("yes", "From Wikipedia infobox"), ("no", "Not from Wikipedia infobox"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(date_evidence__property="wikipedia_infobox")
        if self.value() == "no":
            return queryset.exclude(date_evidence__property="wikipedia_infobox")
        return queryset


class GoldenEndpointFilter(admin.SimpleListFilter):
    title = "golden set"
    parameter_name = "golden"

    def lookups(self, request, model_admin):
        return (("yes", "Golden endpoint"), ("no", "No golden endpoint"))

    def queryset(self, request, queryset):
        golden = Q(from_work__depth="editorial", from_work__is_demo=False) | Q(to_work__depth="editorial", to_work__is_demo=False)
        if self.value() == "yes":
            return queryset.filter(golden)
        if self.value() == "no":
            return queryset.exclude(golden)
        return queryset


class UndatedEndpointFilter(admin.SimpleListFilter):
    title = "endpoint date"
    parameter_name = "undated_endpoint"

    def lookups(self, request, model_admin):
        return (("yes", "Has undated endpoint"), ("no", "Both endpoints dated"))

    def queryset(self, request, queryset):
        undated = Q(from_work__first_publication_year__isnull=True) | Q(to_work__first_publication_year__isnull=True)
        if self.value() == "yes":
            return queryset.filter(undated)
        if self.value() == "no":
            return queryset.exclude(undated)
        return queryset


@admin.register(Work)
class WorkAdmin(admin.ModelAdmin):
    list_display = (
        "title_link", "work_type", "first_publication_year", "date_review",
        "visibility", "depth", "credit_count", "relationship_count", "source_count",
        "image_status",
    )
    list_display_links = ("title_link",)
    list_filter = (
        "visibility", "work_type", "depth", "is_demo", HasImageFilter, HasDateFilter,
        WikipediaDateFilter,
    )
    search_fields = (
        "title", "description", "identifiers__value", "credits__agent__name",
        "source_records__external_key",
    )
    prepopulated_fields = {"slug": ("title",)}
    inlines = (CreditInline, VersionInline, WorkSourceInline, ExternalIdentifierInline)
    list_select_related = ("work_type",)
    ordering = ("title", "first_publication_year", "id")
    readonly_fields = ("image_preview", "public_link", "created_at", "updated_at")
    fieldsets = (
        ("Identity", {"fields": ("title", "slug", "work_type", "description")}),
        ("Dates", {"fields": ("first_publication_date_text", "first_publication_year", "date_kind", "date_evidence")}),
        ("Catalog state", {"fields": ("visibility", "depth", "completion_status", "is_demo", "public_link")}),
        ("Image", {"fields": ("image_url", "image_source_url", "image_attribution", "image_license", "image_preview")}),
        ("Record", {"fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _credit_count=Count("credits", distinct=True),
            _relationship_count=Count("outgoing_relationships", distinct=True) + Count("incoming_relationships", distinct=True),
            _source_count=Count("source_records", distinct=True),
        )

    def get_search_results(self, request, queryset, search_term):
        results, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        return (results.distinct() if may_have_duplicates else results), may_have_duplicates

    @admin.display(description="Title", ordering="title")
    def title_link(self, obj):
        return format_html('<a href="{}">{}</a>', reverse("admin:catalog_work_change", args=(obj.pk,)), obj.title)

    @admin.display(description="Date detail")
    def date_review(self, obj):
        if not obj.first_publication_date_text:
            return "—"
        evidence = obj.date_evidence if isinstance(obj.date_evidence, dict) else {}
        suffix = " · unverified" if evidence.get("meaning_unverified") else ""
        return format_html(
            "{}<br><small>{}{}</small>",
            obj.first_publication_date_text,
            obj.get_date_kind_display(),
            suffix,
        )

    @admin.display(description="Credits", ordering="_credit_count")
    def credit_count(self, obj):
        return obj._credit_count

    @admin.display(description="Relationships", ordering="_relationship_count")
    def relationship_count(self, obj):
        return obj._relationship_count

    @admin.display(description="Sources", ordering="_source_count")
    def source_count(self, obj):
        return obj._source_count

    @admin.display(description="Image")
    def image_status(self, obj):
        if not obj.image_url:
            return "—"
        return format_html(
            '<img src="{}" alt="" style="height:54px;width:auto;max-width:90px;object-fit:cover;border:1px solid #ccc">',
            obj.image_url,
        )

    @admin.display(description="Image preview")
    def image_preview(self, obj):
        if not obj.image_url:
            return "No image"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener"><img src="{}" alt="" style="max-height:240px;max-width:180px;border:1px solid #ccc"></a>'
            '<p style="max-width:280px">{}{}</p>',
            obj.image_source_url or obj.image_url,
            obj.image_url,
            obj.image_license or "License not recorded",
            f" · {obj.image_attribution}" if obj.image_attribution else "",
        )

    @admin.display(description="Public page")
    def public_link(self, obj):
        if obj.visibility != Work.Visibility.PUBLIC:
            return "Not public"
        return format_html('<a href="{}" target="_blank" rel="noopener">Open public page</a>', obj.get_absolute_url())


@admin.register(WorkRedirect)
class WorkRedirectAdmin(admin.ModelAdmin):
    list_display = ("old_work", "canonical_work", "merged_by", "merged_at")
    readonly_fields = ("merged_by", "merged_at")
    autocomplete_fields = ("old_work", "canonical_work")

    def has_add_permission(self, request):
        return request.user.is_staff and request.user.has_perm("catalog.merge_work")

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff and request.user.has_perm("catalog.merge_work")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        redirect_record = merge_works(
            source=obj.old_work, canonical=obj.canonical_work, actor=request.user
        )
        obj.pk = redirect_record.pk
        obj.merged_by = redirect_record.merged_by
        obj.merged_at = redirect_record.merged_at
        obj._state.adding = False


@admin.register(FeaturedWork)
class FeaturedWorkAdmin(admin.ModelAdmin):
    list_display = ("work", "position", "note")
    list_editable = ("position",)
    ordering = ("position", "id")
    autocomplete_fields = ("work",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "work":
            kwargs["queryset"] = Work.objects.filter(visibility=Work.Visibility.PUBLIC)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(WorkRelationship)
class RelationshipAdmin(admin.ModelAdmin):
    list_display = ("from_work_link", "relationship_type", "to_work_link", "review_status", "authorization_status", "source", "evidence_link", "edit_link")
    list_display_links = None
    list_filter = ("relationship_type", "review_status", "source", GoldenEndpointFilter)
    search_fields = ("from_work__title", "to_work__title", "scope_note", "evidence")
    autocomplete_fields = ("from_work", "to_work")
    list_select_related = ("from_work", "to_work", "relationship_type", "source")
    list_per_page = 50
    readonly_fields = ("evidence_view",)

    @admin.display(description="From work", ordering="from_work__title")
    def from_work_link(self, obj):
        return format_html('<a href="{}">{}</a>', reverse("admin:catalog_work_change", args=(obj.from_work_id,)), obj.from_work.title)

    @admin.display(description="To work", ordering="to_work__title")
    def to_work_link(self, obj):
        return format_html('<a href="{}">{}</a>', reverse("admin:catalog_work_change", args=(obj.to_work_id,)), obj.to_work.title)

    @admin.display(description="Edge")
    def edit_link(self, obj):
        return format_html('<a href="{}">Inspect edge</a>', reverse("admin:catalog_workrelationship_change", args=(obj.pk,)))

    @admin.display(description="Evidence")
    def evidence_link(self, obj):
        return "Yes" if obj.evidence else "—"

    @admin.display(description="Evidence JSON")
    def evidence_view(self, obj):
        if not obj.evidence:
            return "No evidence recorded."
        return format_html("<pre style='white-space:pre-wrap;max-width:900px'>{}</pre>", json.dumps(obj.evidence, indent=2, sort_keys=True))

    def save_model(self, request, obj, form, change):
        obj.save(publish_event=True)


class ImportItemInline(admin.TabularInline):
    model = ImportItem
    extra = 0
    can_delete = False
    readonly_fields = ("external_key", "status", "work", "message")

class ImportRelationshipProposalInline(admin.TabularInline):
    model = ImportRelationshipProposal
    extra = 0
    can_delete = False
    readonly_fields = ("statement_id", "from_work", "relationship_type", "to_work", "status", "evidence")


@admin.register(ImportRun)
class ImportRunAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "status", "started_at", "finished_at", "seed_count", "item_count", "proposal_count", "stat_summary")
    list_filter = ("status", "source")
    readonly_fields = ("inspection_links", "source", "status", "requested_keys", "manifest", "importer_version", "stats", "started_at", "finished_at")
    list_select_related = ("source",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _item_count=Count("items", distinct=True),
            _proposal_count=Count("relationship_proposals", distinct=True),
        )

    @admin.display(description="Inspect")
    def inspection_links(self, obj):
        return format_html(
            '<a href="{}?run__id__exact={}">Import items ({})</a> · '
            '<a href="{}?run__id__exact={}">Relationship proposals ({})</a>',
            reverse("admin:catalog_importitem_changelist"), obj.pk, obj._item_count,
            reverse("admin:catalog_importrelationshipproposal_changelist"), obj.pk, obj._proposal_count,
        )

    @admin.display(description="Seeds")
    def seed_count(self, obj):
        return len(obj.requested_keys or [])

    @admin.display(description="Items", ordering="_item_count")
    def item_count(self, obj):
        return obj._item_count

    @admin.display(description="Proposals", ordering="_proposal_count")
    def proposal_count(self, obj):
        return obj._proposal_count

    @admin.display(description="Stats")
    def stat_summary(self, obj):
        stats = obj.stats or {}
        keys = ("created", "updated", "unchanged", "conflicted", "failed", "relationships_proposed", "truncated", "error")
        return "; ".join(f"{key}={stats[key]}" for key in keys if key in stats) or "—"


@admin.register(ImportItem)
class ImportItemAdmin(admin.ModelAdmin):
    list_display = ("run", "external_key", "status", "work", "message")
    list_filter = ("status", "run")
    search_fields = ("external_key", "work__title", "message")
    list_select_related = ("run", "work")
    list_per_page = 100

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(ImportRelationshipProposal)
class ImportRelationshipProposalAdmin(admin.ModelAdmin):
    list_display = ("statement_short", "from_work", "relationship_type", "to_work", "endpoint_state", "status", "run")
    list_filter = ("status", "relationship_type", "run", "from_work__work_type", GoldenEndpointFilter, UndatedEndpointFilter)
    search_fields = ("statement_id", "from_work__title", "to_work__title")
    readonly_fields = ("run", "statement_id", "from_work", "to_work", "relationship_type", "source", "evidence", "status", "reviewer", "reviewed_at")
    list_select_related = ("from_work", "to_work", "relationship_type", "source", "run")
    list_per_page = 100
    actions = ("approve_selected", "publish_approved_endpoints")

    @admin.display(description="Statement")
    def statement_short(self, obj):
        return obj.statement_id[:80]

    @admin.display(description="Endpoints")
    def endpoint_state(self, obj):
        return f"{obj.from_work.visibility[0].upper()} → {obj.to_work.visibility[0].upper()}"

    @admin.action(description="Approve selected relationship proposals")
    def approve_selected(self, request, queryset):
        pending = queryset.filter(status=ImportRelationshipProposal.Status.PENDING)
        approved = 0
        for proposal in pending.select_related("from_work", "to_work", "relationship_type", "source"):
            proposal.approve(request.user)
            approved += 1
        self.message_user(request, f"Approved {approved} relationship proposal(s).")

    @admin.action(description="Publish works from selected approved proposals")
    def publish_approved_endpoints(self, request, queryset):
        approved = queryset.filter(status=ImportRelationshipProposal.Status.APPROVED)
        work_ids = set(approved.values_list("from_work_id", flat=True))
        work_ids.update(approved.values_list("to_work_id", flat=True))
        published = 0
        for work in Work.objects.filter(pk__in=work_ids, visibility=Work.Visibility.DRAFT):
            work.visibility = Work.Visibility.PUBLIC
            work.save(update_fields=("visibility", "updated_at"))
            published += 1
        self.message_user(request, f"Published {published} draft work(s).")

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(SourceRecord)
class SourceRecordAdmin(admin.ModelAdmin):
    list_display = ("external_key", "source", "matched_work", "payload_size", "retrieved_at")
    list_filter = ("source", "retrieved_at")
    search_fields = ("external_key", "matched_work__title")
    readonly_fields = ("source", "external_key", "payload_hash", "raw_payload", "retrieved_at", "payload_preview")
    list_select_related = ("source", "matched_work")

    @admin.display(description="Payload bytes", ordering="payload_hash")
    def payload_size(self, obj):
        try:
            return len(json.dumps(obj.raw_payload, separators=(",", ":")).encode())
        except (TypeError, ValueError):
            return "—"

    @admin.display(description="Payload preview")
    def payload_preview(self, obj):
        text = json.dumps(obj.raw_payload, indent=2, sort_keys=True)
        return format_html("<pre style='white-space:pre-wrap;max-width:1000px;max-height:600px;overflow:auto'>{}</pre>", text[:20000])


@admin.register(ImportedWorkState)
class ImportedWorkStateAdmin(admin.ModelAdmin):
    list_display = ("source_record", "imported_title", "imported_date_text", "imported_year")
    search_fields = ("imported_title", "source_record__external_key")
    readonly_fields = ("source_record", "imported_title", "imported_date_text", "imported_year")


@admin.register(ExternalIdentifier)
class ExternalIdentifierAdmin(admin.ModelAdmin):
    list_display = ("work", "scheme", "value")
    list_filter = ("scheme",)
    search_fields = ("work__title", "value")
    list_select_related = ("work",)
    autocomplete_fields = ("work",)


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "wikidata_id", "openlibrary_key", "credit_count")
    list_filter = ("kind",)
    search_fields = ("name", "wikidata_id", "openlibrary_key")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_credit_count=Count("credits", distinct=True))

    @admin.display(description="Credits", ordering="_credit_count")
    def credit_count(self, obj):
        return obj._credit_count


@admin.register(Credit)
class CreditAdmin(admin.ModelAdmin):
    list_display = ("work", "agent", "role", "billing_order", "source")
    list_filter = ("role", "source")
    search_fields = ("work__title", "agent__name")
    list_select_related = ("work", "agent", "source")
    autocomplete_fields = ("work", "agent")


@admin.register(RelationshipType)
class RelationshipTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "inverse_label", "category")
    list_filter = ("category",)
    search_fields = ("code", "label", "inverse_label")


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "url", "record_count")
    list_filter = ("kind",)
    search_fields = ("title", "url", "notes")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_record_count=Count("records", distinct=True))

    @admin.display(description="Records", ordering="_record_count")
    def record_count(self, obj):
        return obj._record_count


@admin.register(WorkType)
class WorkTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "medium", "work_count")
    list_filter = ("medium",)
    search_fields = ("code", "label")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_work_count=Count("works", distinct=True))

    @admin.display(description="Works", ordering="_work_count")
    def work_count(self, obj):
        return obj._work_count


@admin.register(Release)
class ReleaseAdmin(admin.ModelAdmin):
    list_display = ("title", "version", "format", "publication_date_text", "publisher_statement", "openlibrary_key")
    list_filter = ("format",)
    search_fields = ("title", "edition_name", "openlibrary_key", "version__work__title")
    list_select_related = ("version",)


@admin.register(Version)
class VersionAdmin(admin.ModelAdmin):
    list_display = ("work", "label", "kind", "language", "runtime_seconds")
    list_filter = ("kind", "language")
    search_fields = ("work__title", "label", "title")
    list_select_related = ("work",)


@admin.register(WorkSource)
class WorkSourceAdmin(admin.ModelAdmin):
    list_display = ("work", "source", "note")
    list_filter = ("source",)
    search_fields = ("work__title", "note")
    list_select_related = ("work", "source")


@admin.register(MediaList)
class MediaListAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "visibility", "entry_count", "updated_at")
    list_filter = ("visibility",)
    search_fields = ("title", "description", "owner__username")
    list_select_related = ("owner",)
    prepopulated_fields = {"slug": ("title",)}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_entry_count=Count("entries", distinct=True))

    @admin.display(description="Entries", ordering="_entry_count")
    def entry_count(self, obj):
        return obj._entry_count


@admin.register(MediaListEntry)
class MediaListEntryAdmin(admin.ModelAdmin):
    list_display = ("media_list", "work", "position", "created_at")
    list_filter = ("media_list",)
    search_fields = ("media_list__title", "work__title")
    list_select_related = ("media_list", "work")


admin.site.site_header = "Open Media Atlas administration"
admin.site.site_title = "OMA admin"
admin.site.index_title = "Catalog inspection"

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError

from .models import ContributionProposal, ContributionRevision


class ContributionReviewForm(forms.ModelForm):
    decision = forms.ChoiceField(choices=(("", "Leave pending"), ("approve", "Approve"),
        ("clarify", "Request clarification"), ("reject", "Reject")), required=False)
    reconcile_conflict = forms.BooleanField(required=False, help_text="I inspected the current catalog value and explicitly reconciled this conflict.")

    class Meta:
        model = ContributionProposal
        fields = ("reviewer_explanation",)

    def clean(self):
        data = super().clean()
        if data.get("decision") in {"reject", "clarify"} and not data.get("reviewer_explanation", "").strip():
            self.add_error(None, "Enter a reviewer explanation before rejecting or requesting clarification.")
        return data


@admin.register(ContributionProposal)
class ContributionProposalAdmin(admin.ModelAdmin):
    form = ContributionReviewForm
    list_display = ("id", "kind", "work", "submitted_by", "status", "conflict", "submitted_at")
    list_filter = ("status", "kind", "submitted_at")
    search_fields = ("work__title", "submitted_by__username", "explanation", "source_url")
    readonly_fields = ("kind", "status", "submitted_by", "work", "field_name", "value_at_submission",
        "current_value_display", "proposed_value", "target_access_link", "related_work", "relationship_type", "direction_display",
        "work_updated_at", "related_work_updated_at", "explanation", "source_link", "submitted_at",
        "reviewer", "reviewed_at", "supersedes")
    fields = readonly_fields + ("reviewer_explanation", "decision", "reconcile_conflict")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm("catalog.review_contributionproposal")

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("catalog.review_contributionproposal")

    @admin.display(boolean=True, description="Conflict")
    def conflict(self, obj): return obj.has_conflict
    @admin.display(description="Current catalog value")
    def current_value_display(self, obj): return obj.current_value
    @admin.display(description="Relationship direction")
    def direction_display(self, obj):
        return f"{obj.work.title} — {obj.relationship_type.label} — {obj.related_work.title}" if obj.relationship_type_id else "—"
    @admin.display(description="Supporting source")
    def source_link(self, obj):
        from django.utils.html import format_html
        return format_html('<a href="{}" rel="nofollow noopener noreferrer">{}</a>', obj.source_url, obj.source_url)

    def save_model(self, request, obj, form, change):
        decision = form.cleaned_data.get("decision")
        if decision:
            if decision == "clarify":
                obj.request_clarification(reviewer=request.user, explanation=obj.reviewer_explanation)
            else:
                obj.review(reviewer=request.user, approve=decision == "approve",
                    explanation=obj.reviewer_explanation, reconcile=form.cleaned_data.get("reconcile_conflict", False))
            messages.success(request, f"Proposal {obj.status}.")


@admin.register(ContributionRevision)
class ContributionRevisionAdmin(admin.ModelAdmin):
    list_display = ("work", "kind", "contributor", "reviewer", "created_at")
    readonly_fields = ("proposal", "work", "contributor", "reviewer", "kind", "field_name", "previous_value",
                       "new_value", "explanation", "source_url", "created_at")
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ("label", "vocabulary", "category", "identifier")
    list_filter = ("vocabulary", "category")
    search_fields = ("label", "identifier", "description", "source_identifier")


class WorkTermReviewForm(forms.ModelForm):
    decision = forms.ChoiceField(
        choices=(("", "Leave pending"), ("accept", "Accept"), ("reject", "Reject")),
        required=False,
    )

    class Meta:
        model = WorkTermAssignment
        fields = ("reviewer_note",)

    def clean(self):
        data = super().clean()
        if data.get("decision") == "reject" and not data.get("reviewer_note", "").strip():
            self.add_error(None, "Enter a reviewer note before rejecting.")
        return data


@admin.register(WorkTermAssignment)
class WorkTermAssignmentAdmin(admin.ModelAdmin):
    form = WorkTermReviewForm
    list_display = ("work", "term", "review_state", "submitted_by", "submitted_at")
    list_filter = ("review_state", "term__vocabulary", "term__category")
    readonly_fields = (
        "work", "term", "review_state", "source", "source_url", "provenance_note",
        "submitted_by", "submitted_at", "reviewer", "reviewed_at",
    )
    fields = readonly_fields + ("reviewer_note", "decision")

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False
    def has_view_permission(self, request, obj=None):
        return request.user.has_perm("catalog.review_worktermassignment")
    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("catalog.review_worktermassignment")

    def save_model(self, request, obj, form, change):
        decision = form.cleaned_data.get("decision")
        if decision:
            obj.review(
                reviewer=request.user, accept=decision == "accept",
                note=obj.reviewer_note,
            )
            messages.success(request, f"Term suggestion {obj.review_state}.")


from .models import AccessLink


@admin.register(AccessLink)
class AccessLinkAdmin(admin.ModelAdmin):
    list_display = ("provider", "work", "category", "version", "release", "active", "last_checked")
    list_filter = ("category", "active")
    search_fields = ("provider", "work__title", "url")
    readonly_fields = ("reviewed_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
