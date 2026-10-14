from django.urls import path
from . import auth_views, views

urlpatterns = [
    path("/meta", views.member_meta),
    path("/waiver", views.waiver_text),
    path("/signup", auth_views.signup),
    path("/login", auth_views.login),
    path("/logout", auth_views.logout),
    path("/me", auth_views.me),
    path("/<int:member_id>/payments", views.member_payment),
    path("/<int:member_id>/cancel", views.member_cancel),
    path("/<int:member_id>", views.member_detail),
    path("", views.member_list),
]
