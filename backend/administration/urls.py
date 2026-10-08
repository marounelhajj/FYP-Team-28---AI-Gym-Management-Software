from django.urls import path
from . import auth_views, views

urlpatterns = [
    path("/staff/<int:staff_id>", views.staff_detail),
    path("/staff", views.staff_list),
    path("/roles/<int:role_id>", views.role_detail),
    path("/roles", views.role_list),
    path("/permissions", views.permission_list),
    path("/auth/login", auth_views.login),
    path("/auth/logout", auth_views.logout),
    path("/auth/me", auth_views.me),
]
