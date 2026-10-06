from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "catalog"


    def ready(self):
        from . import library_signals  # noqa: F401
