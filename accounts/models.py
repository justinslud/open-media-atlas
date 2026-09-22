from django.conf import settings
from django.db import models


class EmailVerification(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_verified(self):
        return self.verified_at is not None


class AuthRateLimit(models.Model):
    action = models.CharField(max_length=32)
    key_hash = models.CharField(max_length=64)
    window_start = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("action", "key_hash"), name="unique_auth_rate_limit")
        ]

