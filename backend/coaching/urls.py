from django.urls import path

from . import views

# The member's own view lives under /api/members/me/progress (members/urls.py).
urlpatterns = [
    path("/pt-sessions/<int:session_id>/log", views.session_log),
    path("/clients/<int:member_id>/progress", views.client_progress),
    path("/clients/<int:member_id>/goals", views.add_goal),
    path("/goals/<int:goal_id>", views.goal_detail),
]
