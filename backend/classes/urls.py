from django.urls import path

from . import views

# The member's own booking endpoints live under /api/members/me/classes
# (members/urls.py), next to the rest of their self-service endpoints.
urlpatterns = [
    path("", views.class_list),
    path("/coaches", views.coach_list),
    path("/availability", views.availability),
    path("/pt-hours", views.pt_hours_list),
    path("/pt-hours/<int:hours_id>", views.pt_hours_detail),
    path("/pt-sessions/<int:session_id>/cancel", views.staff_cancel_pt),
    path("/types", views.class_type_list),
    path("/types/<int:type_id>", views.class_type_detail),
    path("/<int:class_id>", views.class_detail),
    path("/<int:class_id>/cancel", views.cancel_class),
]
