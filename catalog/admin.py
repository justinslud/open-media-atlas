from django.contrib import admin
from .models import (Agent, Credit, ExternalIdentifier, FeaturedWork, ImportedWorkState,
    ImportItem, ImportRun, Release, RelationshipType, Source, SourceRecord, Version,
    Work, WorkRelationship, WorkSource, WorkType)
from .models import Agent, Credit, ExternalIdentifier, Release, RelationshipType, Source, Version, Work, WorkRelationship, WorkSource, WorkType


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


@admin.register(WorkRelationship)
class RelationshipAdmin(admin.ModelAdmin):
    list_display = ("from_work", "relationship_type", "to_work", "review_status", "authorization_status")
    list_filter = ("relationship_type", "review_status")
    autocomplete_fields = ("from_work", "to_work")


admin.site.register([Agent, Credit, ExternalIdentifier, Release, RelationshipType, Source, Version, WorkSource, WorkType])


class ImportItemInline(admin.TabularInline):
    model = ImportItem
    extra = 0
    can_delete = False
    readonly_fields = ("external_key", "status", "work", "message")


@admin.register(ImportRun)
class ImportRunAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "status", "started_at", "finished_at", "stats")
    list_filter = ("status", "source")
    readonly_fields = ("source", "status", "requested_keys", "stats", "started_at", "finished_at")
    inlines = (ImportItemInline,)


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


admin.site.register(FeaturedWork)
admin.site.site_header = "Open Media Atlas administration"
admin.site.site_title = "OMA admin"
admin.site.site_header = "Open Media Atlas administration"
admin.site.site_title = "OMA admin"

