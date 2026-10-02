from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("", views.home, name="home"),
    path("discover/", views.discover, name="discover"),
    path("works/<int:pk>/suggest-correction/", views.suggest_correction, name="suggest-correction"),
    path("works/<int:pk>/suggest-relationship/", views.suggest_relationship, name="suggest-relationship"),
    path("works/<int:pk>/suggest-term/", views.suggest_term, name="suggest-term"),
    path("works/<int:work_pk>/add-to-list/", views.add_to_list, name="add-to-list"),
    path("works/<int:pk>/<slug:slug>/", views.work_detail, name="work-detail"),
    path("me/contributions/", views.my_contributions, name="my-contributions"),
    path("me/contributions/<int:pk>/resubmit/", views.resubmit_contribution, name="resubmit-contribution"),
    path("lists/", views.public_lists, name="public-lists"),
    path("lists/<int:pk>/<slug:slug>/", views.list_detail, name="list-detail"),
    path("me/lists/", views.my_lists, name="my-lists"),
    path("me/lists/new/", views.list_create, name="list-create"),
    path("me/lists/<int:pk>/edit/", views.list_edit, name="list-edit"),
    path("me/lists/<int:pk>/delete/", views.list_delete, name="list-delete"),
    path("me/lists/<int:pk>/search/", views.list_work_search, name="list-work-search"),
    path("me/lists/<int:pk>/add/<int:work_pk>/", views.list_add_work, name="list-add-work"),
    path("me/lists/<int:pk>/entries/<int:entry_pk>/", views.list_entry_edit, name="list-entry-edit"),
    path("me/lists/<int:pk>/entries/<int:entry_pk>/remove/", views.list_entry_remove, name="list-entry-remove"),
    path("me/lists/<int:pk>/entries/<int:entry_pk>/<str:direction>/", views.list_entry_move, name="list-entry-move"),
]
