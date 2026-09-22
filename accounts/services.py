import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import EmailVerification


def token_hash(token):
    return hashlib.sha256(f"{settings.SECRET_KEY}:{token}".encode()).hexdigest()


def send_verification(request, user):
    token = secrets.token_urlsafe(32)
    verification, _ = EmailVerification.objects.get_or_create(user=user)
    verification.token_hash = token_hash(token)
    verification.expires_at = timezone.now() + timedelta(hours=settings.EMAIL_VERIFICATION_TIMEOUT_HOURS)
    verification.save(update_fields=("token_hash", "expires_at"))
    url = request.build_absolute_uri(reverse("accounts:verify", args=(user.pk, token)))
    send_mail(
        "Verify your Open Media Atlas email",
        render_to_string("accounts/email/verify.txt", {"username": user.username, "verify_url": url}),
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )

