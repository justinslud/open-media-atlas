import secrets

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordResetView
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from .forms import SignUpForm
from .models import EmailVerification
from .rate_limits import client_key, is_limited
from .services import send_verification, token_hash


def limited_response(request):
    return render(request, "accounts/rate_limited.html", status=429)


class RateLimitedLoginView(LoginView):
    template_name = "accounts/login.html"

    def post(self, request, *args, **kwargs):
        if is_limited("login", client_key(request)):
            return limited_response(request)
        return super().post(request, *args, **kwargs)


class RateLimitedPasswordResetView(PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/email/password_reset.txt"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")

    def post(self, request, *args, **kwargs):
        if is_limited("password_reset", client_key(request)):
            return limited_response(request)
        return super().post(request, *args, **kwargs)


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("accounts:account")
    if request.method == "POST" and is_limited("signup", client_key(request)):
        return limited_response(request)
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        try:
            send_verification(request, user)
            messages.success(request, "Account created. Check your email to verify your address.")
        except Exception:
            messages.error(request, "Account created, but verification email could not be sent. Try again from your account page or contact the administrator.")
        next_url = request.POST.get("next", "")
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect("accounts:account")
    return render(request, "accounts/signup.html", {"form": form, "next": request.GET.get("next", "")})


@login_required
def account(request):
    verification, _ = EmailVerification.objects.get_or_create(user=request.user)
    return render(request, "accounts/account.html", {"verification": verification})


@login_required
@require_POST
def resend_verification(request):
    verification, _ = EmailVerification.objects.get_or_create(user=request.user)
    if verification.is_verified:
        messages.info(request, "Your email address is already verified.")
    elif is_limited("verification", client_key(request, request.user.email)):
        return limited_response(request)
    else:
        try:
            send_verification(request, request.user)
            messages.success(request, "A new verification email was sent.")
        except Exception:
            messages.error(request, "Verification email could not be sent. Try later or contact the administrator.")
    return redirect("accounts:account")


@require_http_methods(["GET", "POST"])
def verify_email(request, user_id, token):
    verification = get_object_or_404(EmailVerification, user_id=user_id)
    valid = (
        not verification.is_verified
        and verification.expires_at is not None
        and verification.expires_at > timezone.now()
        and secrets.compare_digest(verification.token_hash, token_hash(token))
    )
    if request.method == "POST" and valid:
        verification.verified_at = timezone.now()
        verification.token_hash = ""
        verification.expires_at = None
        verification.save(update_fields=("verified_at", "token_hash", "expires_at"))
        messages.success(request, "Your email address is verified.")
        return redirect("accounts:account")
    return render(request, "accounts/verify.html", {"valid": valid})
