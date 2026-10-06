from django import template
from catalog.models import SavedWork, WorkFollow, CollectionFollow

register = template.Library()


@register.inclusion_tag("catalog/_library_control.html", takes_context=True)
def library_control(context, obj, action):
    request = context["request"]
    active = False
    if request.user.is_authenticated:
        cache = getattr(request, "_library_states", None)
        if cache is None:
            cache = request._library_states = {}
        if action not in cache:
            ids = {obj.pk}
            # Restrict state queries to the objects rendered on this page.
            if action == "follow-collection":
                ids.update(row.collection_id for row in context.get("page_obj", ()) if isinstance(row, CollectionFollow))
            else:
                for name in ("works", "fallback_works", "page_obj"):
                    for row in context.get(name, ()):
                        if isinstance(row, WorkFollow):
                            ids.add(row.work_id)
                        elif hasattr(row, "work_type_id"):
                            ids.add(row.pk)
                ids.update(row.work_id for row in context.get("featured_selections", ()))
            model, field = {"save": (SavedWork, "work_id"), "follow-work": (WorkFollow, "work_id"),
                            "follow-collection": (CollectionFollow, "collection_id")}[action]
            cache[action] = {pk: False for pk in ids}
            for pk in model.objects.filter(user=request.user, **{field + "__in": ids}).values_list(field, flat=True):
                cache[action][pk] = True
        if obj.pk not in cache[action]:
            model, field = {"save": (SavedWork, "work_id"), "follow-work": (WorkFollow, "work_id"),
                            "follow-collection": (CollectionFollow, "collection_id")}[action]
            cache[action][obj.pk] = model.objects.filter(user=request.user, **{field: obj.pk}).exists()
        active = cache[action][obj.pk]
    return {"object": obj, "object_label": getattr(obj, "display_title", str(obj)), "action": action, "active": active, "request": request,
            "csrf_token": context.get("csrf_token"), "label": "Save" if action == "save" else "Follow",
            "active_label": "Saved" if action == "save" else "Following"}


@register.simple_tag
def event_summary(event, side):
    snapshot = getattr(event, side)
    works = {work.pk: work.display_title for work in event.works.all()}
    text = f"{works.get(snapshot.get('from'), 'Work')} → {snapshot.get('label', 'relationship')} → {works.get(snapshot.get('to'), 'Work')}"
    if snapshot.get("scope"):
        text += f". {snapshot['scope']}"
    return text
