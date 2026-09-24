import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import AuthRateLimit


LIMITS = {
    "signup": (5, timedelta(hours=1)),
    "login": (10, timedelta(minutes=5)),
    "password_reset": (5, timedelta(hours=1)),
    "verification": (5, timedelta(hours=1)),
    "contribution": (10, timedelta(hours=1)),
}


def client_key(request, identifier=""):
    address = request.META.get("REMOTE_ADDR", "unknown")
    value = f"{address}|{identifier.strip().casefold()}"
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def is_limited(action, key):
    maximum, window = LIMITS[action]
    now = timezone.now()
    try:
        with transaction.atomic():
            row = AuthRateLimit.objects.select_for_update().filter(action=action, key_hash=key).first()
            if row is None:
                try:
                    AuthRateLimit.objects.create(action=action, key_hash=key, window_start=now, attempts=1)
                    return False
                except IntegrityError:
                    # A concurrent worker created it; retry under a new transaction.
                    raise
            if row.window_start <= now - window:
                row.window_start = now
                row.attempts = 1
            else:
                row.attempts += 1
            row.save(update_fields=("window_start", "attempts"))
            return row.attempts > maximum
    except IntegrityError:
        with transaction.atomic():
            row = AuthRateLimit.objects.select_for_update().get(action=action, key_hash=key)
            row.attempts += 1
            row.save(update_fields=("attempts",))
            return row.attempts > maximum

