from django.urls import path
from . import views

urlpatterns = [
    path("/meta", views.plan_meta),
    path("/pricing", views.branch_pricing),
    path("/promotions/<int:promotion_id>", views.promotion_detail),
    path("/promotions", views.promotion_list),
    path("/<int:plan_id>", views.plan_detail),
    path("", views.plan_list),
]
