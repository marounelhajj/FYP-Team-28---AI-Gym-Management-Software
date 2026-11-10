from django.urls import path

from . import calls, views

urlpatterns = [
    path("/at-risk", views.at_risk_list),
    path("/refresh", views.refresh),
    path("/capacity", views.capacity),
    path("/calls", calls.log_call),
    path("/members/<int:member_id>/calls", calls.member_calls),
]
