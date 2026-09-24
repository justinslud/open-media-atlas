from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("catalog", "0005_agent_openlibrary_key_importrun_importer_version_and_more")]

    operations = [
        migrations.AlterField(
            model_name="importrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("running", "Running"),
                    ("completed", "Completed"),
                    ("completed_with_errors", "Completed with errors"),
                    ("failed", "Failed"),
                ],
                default="running",
                max_length=30,
            ),
        )
    ]
