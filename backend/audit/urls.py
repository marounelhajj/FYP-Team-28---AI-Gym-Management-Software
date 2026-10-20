from django.urls import path
from . import views

urlpatterns = [
    path("/meta", views.audit_log_meta),
    path("", views.audit_log_list),
]
