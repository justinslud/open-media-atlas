from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("", views.home, name="home"),
    path("discover/", views.discover, name="discover"),
    path("works/<int:pk>/<slug:slug>/", views.work_detail, name="work-detail"),
]
