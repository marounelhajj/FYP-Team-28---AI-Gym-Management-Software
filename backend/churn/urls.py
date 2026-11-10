from django.urls import path

from . import views

urlpatterns = [
    path("/at-risk", views.at_risk_list),
    path("/refresh", views.refresh),
]
