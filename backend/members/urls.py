from django.urls import path
from . import views

urlpatterns = [
    path("/meta", views.member_meta),
    path("/<int:member_id>", views.member_detail),
    path("", views.member_list),
]
