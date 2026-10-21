from django.urls import path
from . import views

urlpatterns = [
    path("", views.training_event_list),
]
