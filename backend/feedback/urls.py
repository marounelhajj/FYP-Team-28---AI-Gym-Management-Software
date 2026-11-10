from django.urls import path

from . import views

# The member's own endpoints live under /api/members/me/feedback
# (members/urls.py); this is the coach's view of the ratings left for them.
urlpatterns = [
    path("/me", views.coach_ratings),
]
