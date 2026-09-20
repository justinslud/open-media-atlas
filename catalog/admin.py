from django.contrib import admin
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
admin.site.site_header = "Open Media Atlas administration"
admin.site.site_title = "OMA admin"

