import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.conf import settings
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class WorkType(models.Model):
    code = models.SlugField(primary_key=True)
    label = models.CharField(max_length=80)
    medium = models.CharField(max_length=40)

    def __str__(self):
        return self.label


class Work(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        DRAFT = "draft", "Draft"
        SUPPRESSED = "suppressed", "Suppressed"

    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=320)
    work_type = models.ForeignKey(WorkType, on_delete=models.PROTECT, related_name="works")
    description = models.TextField(blank=True)
    first_publication_date_text = models.CharField(max_length=80, blank=True)
    first_publication_year = models.IntegerField(null=True, blank=True)
    completion_status = models.CharField(max_length=30, default="unknown")
    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.DRAFT, db_index=True)
    depth = models.CharField(max_length=20, choices=[("index", "Index record"), ("editorial", "Editorial")], default="index")
    is_demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("title", "first_publication_year", "id")
        indexes = [
            models.Index(fields=("visibility", "work_type")),
            models.Index(fields=("visibility", "first_publication_year")),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("work-detail", kwargs={"pk": self.pk, "slug": self.slug})

    def __str__(self):
        return f"{self.title} ({self.first_publication_date_text or 'date unknown'})"


class MediaList(models.Model):
    """A member-curated, ordered collection (separate from homepage curation)."""

    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private"
        PUBLIC = "public", "Public"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="media_lists")
    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, blank=True)
    description = models.TextField(blank=True, max_length=1000)
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PRIVATE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-id")

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:140] or "list"
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("list-detail", kwargs={"pk": self.pk, "slug": self.slug})

    def __str__(self):
        return self.title


class MediaListEntry(models.Model):
    media_list = models.ForeignKey(MediaList, on_delete=models.CASCADE, related_name="entries")
    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="list_entries")
    commentary = models.TextField(blank=True, max_length=1000)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(fields=("media_list", "work"), name="unique_work_per_media_list"),
            models.UniqueConstraint(fields=("media_list", "position"), name="unique_position_per_media_list"),
        ]

    def __str__(self):
        return f"{self.media_list}: {self.work}"


class Agent(models.Model):
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, choices=[("person", "Person"), ("organization", "Organization")])
    openlibrary_key = models.CharField(max_length=40, unique=True, null=True, blank=True)
    wikidata_id = models.CharField(max_length=20, unique=True, null=True, blank=True)

    def __str__(self):
        return self.name


class Credit(models.Model):
    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="credits")
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="credits")
    role = models.CharField(max_length=60)
    credited_as = models.CharField(max_length=200, blank=True)
    billing_order = models.PositiveIntegerField(default=0)
    source = models.ForeignKey("Source", on_delete=models.PROTECT, null=True, blank=True, related_name="credits")

    class Meta:
        ordering = ("billing_order", "id")
        constraints = [models.UniqueConstraint(fields=("work", "agent", "role"), name="unique_work_agent_role")]


class Version(models.Model):
    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="versions")
    label = models.CharField(max_length=200)
    kind = models.CharField(max_length=30, choices=[("original", "Original"), ("translation", "Translation"), ("cut", "Cut"), ("revision", "Revision"), ("unresolved", "Unresolved")])
    title = models.CharField(max_length=300, blank=True)
    language = models.CharField(max_length=80, blank=True)
    contributor_note = models.CharField(max_length=200, blank=True)
    first_available_date_text = models.CharField(max_length=80, blank=True)
    runtime_seconds = models.PositiveIntegerField(null=True, blank=True)
    page_mode = models.CharField(max_length=20, choices=[("embedded", "Embedded"), ("standalone", "Standalone")], default="embedded")
    page_mode_reason = models.TextField(blank=True)

    class Meta:
        ordering = ("id",)
        constraints = [models.UniqueConstraint(fields=("work", "label"), name="unique_version_label_per_work")]

    def __str__(self):
        return f"{self.work.title}: {self.label}"


class Release(models.Model):
    version = models.ForeignKey(Version, on_delete=models.CASCADE, related_name="releases")
    title = models.CharField(max_length=300)
    edition_name = models.CharField(max_length=200, blank=True)
    format = models.CharField(max_length=80, blank=True)
    publication_date_text = models.CharField(max_length=80, blank=True)
    publisher_statement = models.CharField(max_length=200, blank=True)
    pages = models.PositiveIntegerField(null=True, blank=True)
    openlibrary_key = models.CharField(max_length=40, unique=True, null=True, blank=True)

    class Meta:
        ordering = ("id",)


class Source(models.Model):
    title = models.CharField(max_length=300)
    kind = models.CharField(max_length=30, default="webpage")
    url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.title


class SourceRecord(models.Model):
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="records")
    external_key = models.CharField(max_length=200)
    matched_work = models.ForeignKey(Work, on_delete=models.SET_NULL, null=True, blank=True, related_name="source_records")
    payload_hash = models.CharField(max_length=64)
    raw_payload = models.JSONField()
    retrieved_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=("source", "external_key"), name="unique_source_external_key")]

    def __str__(self):
        return f"{self.source}: {self.external_key}"


class ImportedWorkState(models.Model):
    """Last accepted supplier values, used to avoid overwriting editorial changes."""

    source_record = models.OneToOneField(SourceRecord, on_delete=models.CASCADE, related_name="work_state")
    imported_title = models.CharField(max_length=300)
    imported_date_text = models.CharField(max_length=80, blank=True)
    imported_year = models.IntegerField(null=True, blank=True)


class ImportRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        COMPLETED_WITH_ERRORS = "completed_with_errors", "Completed with errors"
        FAILED = "failed", "Failed"

    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="import_runs")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.RUNNING)
    requested_keys = models.JSONField(default=list)
    stats = models.JSONField(default=dict)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    manifest = models.JSONField(default=dict, blank=True)
    importer_version = models.CharField(max_length=40, blank=True)

    def __str__(self):
        return f"{self.source} import {self.pk} ({self.status})"


class ImportItem(models.Model):
    run = models.ForeignKey(ImportRun, on_delete=models.CASCADE, related_name="items")
    external_key = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=[("created", "Created"), ("updated", "Updated"), ("unchanged", "Unchanged"), ("skipped", "Skipped"), ("conflicted", "Conflicted"), ("failed", "Failed")])
    work = models.ForeignKey(Work, on_delete=models.SET_NULL, null=True, blank=True)
    message = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("run", "external_key"), name="unique_import_run_item")]


class FeaturedWork(models.Model):
    work = models.OneToOneField(Work, on_delete=models.CASCADE, related_name="featured")
    position = models.PositiveSmallIntegerField(default=0)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ("position", "id")

    def __str__(self):
        return self.work.title


class WorkSource(models.Model):
    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="source_links")
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="work_links")
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("work", "source"), name="unique_work_source")]


class RelationshipType(models.Model):
    code = models.SlugField(primary_key=True)
    label = models.CharField(max_length=100, help_text="From work to target, e.g. Adapted from")
    inverse_label = models.CharField(max_length=100, help_text="Target work to source, e.g. Adaptations")
    category = models.CharField(max_length=30, default="derivation")

    def __str__(self):
        return self.label


class WorkRelationship(models.Model):
    from_work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="outgoing_relationships")
    to_work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="incoming_relationships")
    relationship_type = models.ForeignKey(RelationshipType, on_delete=models.PROTECT)
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="relationships")
    scope_note = models.CharField(max_length=300, blank=True)
    review_status = models.CharField(max_length=20, choices=[("accepted", "Accepted"), ("unreviewed", "Unreviewed"), ("disputed", "Disputed")], default="unreviewed")
    authorization_status = models.CharField(max_length=20, default="unknown")
    evidence = models.JSONField(default=dict, blank=True, help_text="Source statement, references, qualifiers, rank, and retrieval metadata.")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("from_work", "to_work", "relationship_type"), name="unique_work_relationship"),
            models.CheckConstraint(condition=~models.Q(from_work=models.F("to_work")), name="relationship_not_self"),
        ]

    def clean(self):
        if self.from_work_id == self.to_work_id:
            raise ValidationError("A work cannot relate to itself.")

    def __str__(self):
        return f"{self.from_work} {self.relationship_type.label} {self.to_work}"

    @property
    def evidence_url(self):
        return self.evidence.get("source_url", "") if isinstance(self.evidence, dict) else ""


class ImportRelationshipProposal(models.Model):
    """A supplier assertion kept inert until an editor explicitly accepts it."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    run = models.ForeignKey(ImportRun, on_delete=models.CASCADE, related_name="relationship_proposals")
    statement_id = models.CharField(max_length=200)
    from_work = models.ForeignKey(Work, on_delete=models.PROTECT, related_name="import_outgoing_proposals")
    to_work = models.ForeignKey(Work, on_delete=models.PROTECT, related_name="import_incoming_proposals")
    relationship_type = models.ForeignKey(RelationshipType, on_delete=models.PROTECT)
    source = models.ForeignKey(Source, on_delete=models.PROTECT)
    evidence = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("run", "statement_id"), name="unique_statement_per_import_run")]

    def approve(self, reviewer):
        """Publish only the assertion; draft endpoint visibility remains a separate decision."""
        with transaction.atomic():
            proposal = ImportRelationshipProposal.objects.select_for_update().get(pk=self.pk)
            relationship, _ = WorkRelationship.objects.update_or_create(
                from_work=proposal.from_work, to_work=proposal.to_work,
                relationship_type=proposal.relationship_type,
                defaults={"source": proposal.source, "scope_note": "Wikidata P144 (based on) assertion; editor approved.",
                          "review_status": "accepted", "authorization_status": "unknown", "evidence": proposal.evidence},
            )
            proposal.status = self.Status.APPROVED
            proposal.reviewer = reviewer
            proposal.reviewed_at = timezone.now()
            proposal.save(update_fields=("status", "reviewer", "reviewed_at"))
        self.refresh_from_db()
        return relationship


class ExternalIdentifier(models.Model):
    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="identifiers")
    scheme = models.CharField(max_length=60)
    value = models.CharField(max_length=200)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("work", "scheme", "value"), name="unique_external_identifier")]

class ContributionProposal(models.Model):
    class Kind(models.TextChoices):
        CORRECTION = "correction", "Correction"
        RELATIONSHIP = "relationship", "Relationship"
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="contribution_proposals")
    work = models.ForeignKey(Work, on_delete=models.PROTECT, related_name="proposals")
    field_name = models.CharField(max_length=40, blank=True)
    value_at_submission = models.TextField(blank=True)
    proposed_value = models.TextField(blank=True)
    related_work = models.ForeignKey(Work, on_delete=models.PROTECT, null=True, blank=True, related_name="relationship_proposals")
    relationship_type = models.ForeignKey(RelationshipType, on_delete=models.PROTECT, null=True, blank=True)
    work_updated_at = models.DateTimeField()
    related_work_updated_at = models.DateTimeField(null=True, blank=True)
    explanation = models.TextField(max_length=2000)
    source_url = models.URLField(max_length=500)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="reviewed_contributions")
    reviewer_explanation = models.TextField(blank=True, max_length=1000)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-submitted_at", "-id")
        permissions = [("review_contributionproposal", "Can approve or reject contribution proposals")]

    @property
    def current_value(self):
        if self.kind == self.Kind.CORRECTION:
            return str(getattr(self.work, self.field_name, ""))
        return "Relationship is already present" if WorkRelationship.objects.filter(
            from_work=self.work, to_work=self.related_work, relationship_type=self.relationship_type
        ).exists() else "Relationship is not present"

    @property
    def has_conflict(self):
        if self.kind == self.Kind.CORRECTION:
            return self.current_value != self.value_at_submission
        return (self.work.updated_at != self.work_updated_at or
                self.related_work.updated_at != self.related_work_updated_at or
                WorkRelationship.objects.filter(from_work=self.work, to_work=self.related_work,
                                                relationship_type=self.relationship_type).exists())

    def clean(self):
        super().clean()
        if self.kind == self.Kind.CORRECTION:
            if self.field_name not in {"title", "description", "first_publication_date_text"}:
                raise ValidationError({"field_name": "This field cannot be proposed."})
            if self.related_work_id or self.relationship_type_id:
                raise ValidationError("Correction proposals cannot include a relationship.")
        else:
            if not self.related_work_id or not self.relationship_type_id:
                raise ValidationError("Choose a related work and relationship type.")
            if self.work_id == self.related_work_id:
                raise ValidationError({"related_work": "A work cannot relate to itself."})
        if self.source_url and not self.source_url.lower().startswith(("http://", "https://")):
            raise ValidationError({"source_url": "Use an HTTP or HTTPS source URL."})

    def review(self, *, reviewer, approve, explanation="", reconcile=False):
        if not reviewer.has_perm("catalog.review_contributionproposal"):
            raise PermissionDenied("Explicit reviewer permission is required.")
        with transaction.atomic():
            proposal = ContributionProposal.objects.select_for_update().select_related(
                "work", "related_work", "relationship_type"
            ).get(pk=self.pk)
            if proposal.status != self.Status.PENDING:
                raise ValidationError("This proposal has already been reviewed.")
            if not approve and not explanation.strip():
                raise ValidationError("A reviewer explanation is required when rejecting a proposal.")
            if approve and proposal.has_conflict and not reconcile:
                raise ValidationError("The catalog changed after submission. Reconcile the conflict explicitly before approval.")
            old_value = proposal.current_value
            if approve:
                if proposal.kind == self.Kind.CORRECTION:
                    setattr(proposal.work, proposal.field_name, proposal.proposed_value)
                    fields = [proposal.field_name, "updated_at"]
                    if proposal.field_name == "first_publication_date_text":
                        match = re.search(r"(?<!\d)(1\d{3}|20\d{2})(?!\d)", proposal.proposed_value)
                        proposal.work.first_publication_year = int(match.group(1)) if match else None
                        fields.append("first_publication_year")
                    if proposal.field_name == "title":
                        proposal.work.slug = slugify(proposal.proposed_value)[:320]
                        fields.append("slug")
                    proposal.work.save(update_fields=fields)
                else:
                    source = Source.objects.create(title="Contributor-submitted source", url=proposal.source_url,
                                                   notes="Reviewed supporting source for an approved community relationship.")
                    WorkRelationship.objects.create(from_work=proposal.work, to_work=proposal.related_work,
                        relationship_type=proposal.relationship_type, source=source,
                        scope_note=proposal.explanation[:300], review_status="accepted")
                proposal.status = self.Status.APPROVED
            else:
                proposal.status = self.Status.REJECTED
            proposal.reviewer = reviewer
            proposal.reviewer_explanation = explanation.strip()
            proposal.reviewed_at = timezone.now()
            proposal.save(update_fields=("status", "reviewer", "reviewer_explanation", "reviewed_at"))
            if approve:
                ContributionRevision.objects.create(proposal=proposal, work=proposal.work,
                    contributor=proposal.submitted_by, reviewer=reviewer, kind=proposal.kind,
                    field_name=proposal.field_name, previous_value=old_value,
                    new_value=proposal.proposed_value, explanation=proposal.explanation,
                    source_url=proposal.source_url)
        self.refresh_from_db()

    def __str__(self):
        return f"{self.get_kind_display()} for {self.work} ({self.get_status_display()})"


class ContributionRevision(models.Model):
    proposal = models.OneToOneField(ContributionProposal, on_delete=models.PROTECT, related_name="revision")
    work = models.ForeignKey(Work, on_delete=models.PROTECT, related_name="contribution_revisions")
    contributor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="contribution_revisions")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reviewed_revisions")
    kind = models.CharField(max_length=20, choices=ContributionProposal.Kind.choices)
    field_name = models.CharField(max_length=40, blank=True)
    previous_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    explanation = models.TextField()
    source_url = models.URLField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"Approved {self.kind} for {self.work}"
