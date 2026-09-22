import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AuthRateLimit, EmailVerification
from .rate_limits import LIMITS


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AccountFlowTests(TestCase):
    password = "correct-horse-battery-staple"

    def create_user(self, username="reader", email="reader@example.com"):
        return get_user_model().objects.create_user(username, email, self.password)

    def signup(self, **changes):
        data = {
            "username": "new_reader",
            "email": "reader@example.com",
            "password1": self.password,
            "password2": self.password,
        }
        data.update(changes)
        return self.client.post(reverse("accounts:signup"), data)

    def test_signup_creates_unprivileged_user_and_sends_verification(self):
        response = self.signup()
        user = get_user_model().objects.get(username="new_reader")
        self.assertRedirects(response, reverse("accounts:account"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.user_permissions.count(), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn(user.email, response.content.decode())

    def test_duplicate_username_and_email_are_rejected(self):
        self.create_user()
        response = self.signup(username="reader", email="READER@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists", count=2)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_login_redirect_logout_and_protected_account(self):
        self.create_user()
        account_url = reverse("accounts:account")
        response = self.client.get(account_url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={account_url}")
        response = self.client.post(reverse("accounts:login"), {"username": "reader", "password": self.password, "next": account_url})
        self.assertRedirects(response, account_url)
        self.assertContains(self.client.get(account_url), "reader@example.com")
        self.assertRedirects(self.client.post(reverse("accounts:logout")), reverse("home"))
        self.assertRedirects(self.client.get(account_url), f"{reverse('accounts:login')}?next={account_url}")

    def test_login_rejects_unsafe_redirect(self):
        self.create_user()
        response = self.client.post(reverse("accounts:login"), {"username": "reader", "password": self.password, "next": "https://evil.example/steal"})
        self.assertRedirects(response, reverse("accounts:account"))

    def test_verification_valid_expired_invalid_and_reused_tokens(self):
        self.signup()
        url = re.search(r"http://testserver(/account/verify/\S+)", mail.outbox[0].body).group(1)
        self.assertContains(self.client.get(url), "Confirm")
        self.assertRedirects(self.client.post(url), reverse("accounts:account"))
        self.assertTrue(EmailVerification.objects.get().is_verified)
        self.assertContains(self.client.get(url), "invalid, expired, or has already been used")

        user = self.create_user("second", "second@example.com")
        item = EmailVerification.objects.create(user=user, token_hash="wrong", expires_at=timezone.now() - timedelta(seconds=1))
        self.assertContains(self.client.get(reverse("accounts:verify", args=(user.pk, "bad"))), "invalid, expired")
        self.assertIsNone(item.verified_at)

    def test_password_reset_is_generic_and_token_cannot_be_reused(self):
        user = self.create_user()
        reset_url = reverse("accounts:password_reset")
        existing = self.client.post(reset_url, {"email": user.email})
        generic = self.client.post(reset_url, {"email": "missing@example.com"})
        self.assertRedirects(existing, reverse("accounts:password_reset_done"))
        self.assertRedirects(generic, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        url = re.search(r"http://testserver(/account/reset/\S+)", mail.outbox[0].body).group(1)
        response = self.client.get(url)
        set_url = response.url
        response = self.client.post(set_url, {"new_password1": "new-correct-horse-battery", "new_password2": "new-correct-horse-battery"})
        self.assertRedirects(response, reverse("accounts:password_reset_complete"))
        self.assertContains(self.client.get(url, follow=True), "invalid, expired, or has already been used")

    def test_expired_password_reset_token_is_rejected(self):
        user = self.create_user()
        self.client.post(reverse("accounts:password_reset"), {"email": user.email})
        url = re.search(r"http://testserver(/account/reset/\S+)", mail.outbox[0].body).group(1)
        future = timezone.now().replace(tzinfo=None) + timedelta(days=4)
        with override_settings(PASSWORD_RESET_TIMEOUT=60), patch(
            "django.contrib.auth.tokens.PasswordResetTokenGenerator._now", return_value=future
        ):
            self.assertContains(self.client.get(url, follow=True), "invalid, expired")

    def test_signup_login_and_email_requests_are_rate_limited(self):
        cases = [
            ("signup", reverse("accounts:signup"), {}),
            ("login", reverse("accounts:login"), {"username": "nobody", "password": "wrong"}),
            ("password_reset", reverse("accounts:password_reset"), {"email": "nobody@example.com"}),
        ]
        for action, url, data in cases:
            AuthRateLimit.objects.all().delete()
            maximum = LIMITS[action][0]
            for _ in range(maximum):
                self.client.post(url, data)
            self.assertEqual(self.client.post(url, data).status_code, 429, action)

    def test_catalog_remains_public(self):
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("discover")).status_code, 200)

    def test_state_changes_require_csrf_token(self):
        user = self.create_user()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(user)
        self.assertEqual(csrf_client.post(reverse("accounts:logout")).status_code, 403)
        self.assertEqual(csrf_client.post(reverse("accounts:resend_verification")).status_code, 403)
