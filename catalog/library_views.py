from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST, require_http_methods

from .library import accessible_collections
from .models import SavedWork, WorkFollow, CollectionFollow, Work


def safe_return(request, value):
    return value if value and url_has_allowed_host_and_scheme(
        value, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ) else reverse("accounts:account")


@require_POST
def library_action(request, action, pk):
    if action not in {"save", "follow-work", "follow-collection"} or request.POST.get("active") not in {"0", "1"}:
        return HttpResponseBadRequest("Invalid library action.")
    active = request.POST["active"] == "1"
    next_url = safe_return(request, request.POST.get("next"))
    if not request.user.is_authenticated:
        request.session["library_action"] = {"action": action, "pk": pk, "active": active, "next": next_url}
        return redirect_to_login(reverse("library-resume"))
    with transaction.atomic():
        # Serializing each member's requests makes explicit desired-state operations idempotent.
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        if action == "follow-collection":
            model, field = CollectionFollow, "collection"
            if active:
                obj = get_object_or_404(accessible_collections(request.user).select_for_update(), pk=pk)
            else:
                # Allow removal of an inaccessible subscription without revealing its object.
                model.objects.filter(user=request.user, collection_id=pk).delete()
                obj = None
        else:
            model, field = (SavedWork if action == "save" else WorkFollow), "work"
            if active:
                obj = get_object_or_404(Work.objects.select_for_update().filter(visibility="public", canonical_redirect__isnull=True), pk=pk)
            else:
                model.objects.filter(user=request.user, work_id=pk).delete()
                obj = None
        if active:
            model.objects.get_or_create(user=request.user, **{field: obj})
    if request.headers.get("Accept") == "application/json":
        return JsonResponse({"active": active})
    messages.success(request, {"save": "Saved." if active else "Removed from saved works.",
                              "follow-work": "Following work." if active else "Unfollowed work.",
                              "follow-collection": "Following collection." if active else "Unfollowed collection."}[action])
    return redirect(next_url)


@login_required
@require_http_methods(["GET", "POST"])
def resume(request):
    pending = request.session.get("library_action")
    if not pending:
        return redirect("accounts:account")
    # GET never changes personal state. Confirm the preserved action with a CSRF-protected POST.
    if pending["action"] == "follow-collection":
        obj = get_object_or_404(accessible_collections(request.user), pk=pending["pk"])
    else:
        obj = get_object_or_404(Work, pk=pending["pk"], visibility="public", canonical_redirect__isnull=True)
    if request.method == "POST":
        from django.http import QueryDict
        data = QueryDict(mutable=True)
        data.update({"active": "1" if pending["active"] else "0", "next": pending["next"]})
        request.POST = data
        response = library_action(request, pending["action"], pending["pk"])
        request.session.pop("library_action", None)
        return response
    return render(request, "catalog/library_resume.html", {"object": obj, "pending": pending})
