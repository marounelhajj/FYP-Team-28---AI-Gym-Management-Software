from django.urls import path

from . import attendance, views

# The member's own booking endpoints live under /api/members/me/classes
# (members/urls.py), next to the rest of their self-service endpoints.
urlpatterns = [
    path("", views.class_list),
    path("/me/schedule", views.my_schedule),
    path("/me/pt-hours", views.my_pt_hours),
    path("/me/pt-hours/<int:hours_id>", views.my_pt_hours_detail),
    path("/me/time-off", views.my_time_off),
    path("/me/time-off/<int:time_off_id>", views.my_time_off_detail),
    path("/day", views.class_day),
    path("/coaches", views.coach_list),
    path("/availability", views.availability),
    path("/pt-hours", views.pt_hours_list),
    path("/pt-hours/<int:hours_id>", views.pt_hours_detail),
    path("/pt-sessions/<int:session_id>/cancel", views.staff_cancel_pt),
    path("/types", views.class_type_list),
    path("/types/<int:type_id>", views.class_type_detail),
    path("/<int:class_id>", views.class_detail),
    path("/<int:class_id>/cancel", views.cancel_class),
    path("/<int:class_id>/attendance", attendance.class_attendance),
    path("/<int:class_id>/attendance/walk-ins", attendance.class_walk_in),
    path("/<int:class_id>/member-search", views.class_member_search),
    path("/<int:class_id>/bookings", views.desk_book),
    path("/<int:class_id>/bookings/<int:booking_id>/cancel", views.desk_cancel_booking),
]
