from django.db import migrations


OLD_LABEL = "Inspired or adapted works"
NEW_LABEL = "Works based on this"


def forwards(apps, schema_editor):
    RelationshipType = apps.get_model("catalog", "RelationshipType")
    RelationshipType.objects.filter(code="based-on").update(inverse_label=NEW_LABEL)


def backwards(apps, schema_editor):
    RelationshipType = apps.get_model("catalog", "RelationshipType")
    RelationshipType.objects.filter(code="based-on").update(inverse_label=OLD_LABEL)


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0018_alter_work_date_kind"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
