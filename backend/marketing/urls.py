from django.urls import path
from . import views

urlpatterns = [
    path("/meta", views.marketing_meta),
    path("/report", views.campaign_report),
    path("/campaigns/<int:campaign_id>", views.campaign_detail),
    path("/campaigns", views.campaign_list),
]
