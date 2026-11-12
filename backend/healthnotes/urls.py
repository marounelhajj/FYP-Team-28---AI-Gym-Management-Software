from django.urls import path

from . import views

# The member's own endpoints live under /api/members/me/health
# (members/urls.py); these are the coach's read-only briefings.
urlpatterns = [
    path("/classes/<int:class_id>", views.class_briefing),
    path("/pt-sessions/<int:session_id>", views.pt_briefing),
    path("/members/<int:member_id>", views.member_briefing),
]
