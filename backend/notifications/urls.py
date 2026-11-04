from django.urls import path

from . import views

urlpatterns = [
    path("", views.my_notifications),
    path("/read-all", views.read_all),
    path("/<int:notification_id>/read", views.read_one),
]
