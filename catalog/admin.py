from django.contrib import admin

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


@admin.register(Work)
class WorkAdmin(admin.ModelAdmin):
    list_display = ("title", "work_type", "first_publication_date_text", "visibility", "depth", "is_demo")
    list_filter = ("visibility", "work_type", "depth", "is_demo")
    search_fields = ("title", "description")
    prepopulated_fields = {"slug": ("title",)}
    inlines = (CreditInline, VersionInline, WorkSourceInline)


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
    list_display = ("from_work", "relationship_type", "to_work", "review_status", "authorization_status")
    list_filter = ("relationship_type", "review_status")
    autocomplete_fields = ("from_work", "to_work")


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
    list_display = ("id", "source", "status", "started_at", "finished_at", "stats")
    list_filter = ("status", "source")
    readonly_fields = ("source", "status", "requested_keys", "manifest", "importer_version", "stats", "started_at", "finished_at")
    inlines = (ImportItemInline, ImportRelationshipProposalInline)

@admin.register(ImportRelationshipProposal)
class ImportRelationshipProposalAdmin(admin.ModelAdmin):
    list_display = ("statement_id", "from_work", "relationship_type", "to_work", "status", "run")
    list_filter = ("status", "relationship_type", "run")
    search_fields = ("statement_id", "from_work__title", "to_work__title")
    readonly_fields = ("run", "statement_id", "from_work", "to_work", "relationship_type", "source", "evidence", "status", "reviewer", "reviewed_at")
    actions = ("approve_selected", "publish_approved_endpoints")

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
        published = Work.objects.filter(
            pk__in=work_ids, visibility=Work.Visibility.DRAFT
        ).update(visibility=Work.Visibility.PUBLIC)
        self.message_user(request, f"Published {published} draft work(s).")

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(SourceRecord)
class SourceRecordAdmin(admin.ModelAdmin):
    list_display = ("external_key", "source", "matched_work", "retrieved_at")
    search_fields = ("external_key", "matched_work__title")
    readonly_fields = ("source", "external_key", "payload_hash", "raw_payload", "retrieved_at")


@admin.register(ImportedWorkState)
class ImportedWorkStateAdmin(admin.ModelAdmin):
    list_display = ("source_record", "imported_title", "imported_date_text", "imported_year")
    search_fields = ("imported_title", "source_record__external_key")
    readonly_fields = ("source_record", "imported_title", "imported_date_text", "imported_year")


admin.site.register([Agent, Credit, ExternalIdentifier, Release, RelationshipType, Source, Version, WorkSource, WorkType])
admin.site.register([MediaList, MediaListEntry])
admin.site.site_header = "Open Media Atlas administration"
admin.site.site_title = "OMA admin"

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
        "current_value_display", "proposed_value", "related_work", "relationship_type", "direction_display",
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
