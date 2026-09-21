from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
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
        indexes = [models.Index(fields=("visibility", "work_type"))]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("work-detail", kwargs={"pk": self.pk, "slug": self.slug})

    def __str__(self):
        return f"{self.title} ({self.first_publication_date_text or 'date unknown'})"


class Agent(models.Model):
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, choices=[("person", "Person"), ("organization", "Organization")])

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

    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="import_runs")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.RUNNING)
    requested_keys = models.JSONField(default=list)
    stats = models.JSONField(default=dict)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.source} import {self.pk} ({self.status})"


class ImportItem(models.Model):
    run = models.ForeignKey(ImportRun, on_delete=models.CASCADE, related_name="items")
    external_key = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=[("created", "Created"), ("updated", "Updated"), ("skipped", "Skipped"), ("failed", "Failed")])
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


class ExternalIdentifier(models.Model):
    work = models.ForeignKey(Work, on_delete=models.CASCADE, related_name="identifiers")
    scheme = models.CharField(max_length=60)
    value = models.CharField(max_length=200)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("work", "scheme", "value"), name="unique_external_identifier")]

