from django.urls import path

from . import overview, views

# The member's own endpoints live under /api/members/me/branch-feedback and
# /api/members/me/complaints (members/urls.py); these are the managers'.
urlpatterns = [
    path("/summary", views.summary),
    path("/overview", overview.overview),
    path("/complaints", views.complaint_list),
    path("/complaints/<int:complaint_id>", views.complaint_detail),
    path("/complaints/<int:complaint_id>/messages", views.staff_reply),
    path("/complaints/<int:complaint_id>/escalate", views.escalate_complaint),
]
