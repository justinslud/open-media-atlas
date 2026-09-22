from django.contrib import admin

from .models import AuthRateLimit, EmailVerification


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ("user", "verified_at", "expires_at")
    readonly_fields = ("user", "token_hash", "verified_at", "expires_at")
    search_fields = ("user__username", "user__email")

    def has_add_permission(self, request):
        return False


@admin.register(AuthRateLimit)
class AuthRateLimitAdmin(admin.ModelAdmin):
    list_display = ("action", "window_start", "attempts")
    readonly_fields = ("action", "key_hash", "window_start", "attempts")

    def has_add_permission(self, request):
        return False
