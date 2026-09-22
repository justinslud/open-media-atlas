from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("auth", "0012_alter_user_first_name_max_length")]
    operations = [
        migrations.CreateModel(name="AuthRateLimit", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("action", models.CharField(max_length=32)), ("key_hash", models.CharField(max_length=64)), ("window_start", models.DateTimeField()), ("attempts", models.PositiveIntegerField(default=0))]),
        migrations.CreateModel(name="EmailVerification", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("token_hash", models.CharField(blank=True, max_length=64)), ("expires_at", models.DateTimeField(blank=True, null=True)), ("verified_at", models.DateTimeField(blank=True, null=True)), ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL))]),
        migrations.AddConstraint(model_name="authratelimit", constraint=models.UniqueConstraint(fields=("action", "key_hash"), name="unique_auth_rate_limit")),
    ]
