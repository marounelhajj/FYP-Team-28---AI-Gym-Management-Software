from django.urls import path

from . import views

urlpatterns = [
    path("/me", views.my_pay),
    path("/coaches", views.coach_list),
    path("/coaches/<int:coach_id>", views.coach_detail),
    path("/coaches/<int:coach_id>/rates", views.set_rate),
    path("/coaches/<int:coach_id>/rates/<int:rate_id>", views.remove_rate),
]
