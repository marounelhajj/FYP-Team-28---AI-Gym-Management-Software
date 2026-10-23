from django.urls import path
from . import views

urlpatterns = [
    path("/meta", views.audit_log_meta),
    path("/export", views.audit_log_export),
    path("/retention", views.retention_report),
    path("", views.audit_log_list),
]
