from django.urls import path

from . import views

# The member's own endpoints live under /api/members/me/workouts and
# /api/members/me/metrics (members/urls.py); these are the coach's read-only view.
urlpatterns = [
    path("/clients", views.coach_clients),
    path("/clients/<int:member_id>", views.coach_client_detail),
]
