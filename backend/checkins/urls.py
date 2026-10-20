from django.urls import path
from . import views

urlpatterns = [
    path("/flags", views.flag_list),
    path("/flags/<int:flag_id>/resolve", views.resolve_flag),
    path("/<int:checkin_id>/flag", views.flag_checkin),
    path("/checkout", views.checkout),
    path("", views.checkin_list),
]
