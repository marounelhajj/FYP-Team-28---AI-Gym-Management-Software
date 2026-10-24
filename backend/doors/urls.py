from django.urls import path

from . import views

urlpatterns = [
    path("/self", views.door_self),
    path("/scan", views.door_scan),
    path("/<int:door_id>/rotate-key", views.door_rotate_key),
    path("/<int:door_id>", views.door_detail),
    path("", views.door_list),
]
