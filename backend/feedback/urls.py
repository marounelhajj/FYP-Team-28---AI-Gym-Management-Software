from django.urls import path

from . import views

# The member's own endpoints live under /api/members/me/feedback
# (members/urls.py); these are the coach's view of the ratings left for
# them, and the general manager's branch-by-branch report.
urlpatterns = [
    path("/me", views.coach_ratings),
    path("/report", views.ratings_by_branch),
]
