from django.urls import path
from . import views

urlpatterns = [
    path("/live", views.live_headcount),
    path("/hourly", views.hourly_headcount),
]
