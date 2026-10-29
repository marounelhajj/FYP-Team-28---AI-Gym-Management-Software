from django.urls import path

from billing import views as billing_views
from classes import views as class_views

from . import auth_views, privacy, views

urlpatterns = [
    path("/meta", views.member_meta),
    path("/waiver", views.waiver_text),
    path("/signup", auth_views.signup),
    path("/login", auth_views.login),
    path("/logout", auth_views.logout),
    path("/me", auth_views.me),
    path("/me/qr", auth_views.my_qr),
    path("/me/export", privacy.my_data_export),
    path("/me/delete", privacy.my_data_delete),
    path("/me/payment-method", billing_views.my_payment_method),
    path("/me/billing", billing_views.my_billing),
    path("/me/freeze", views.my_freeze),
    path("/me/resume", views.my_resume),
    path("/me/cancel", views.my_cancel),
    path("/me/classes", class_views.my_classes),
    path("/me/classes/<int:class_id>/book", class_views.book_class),
    path("/me/classes/<int:class_id>/cancel", class_views.cancel_booking),
    path("/me/coaches", class_views.my_coaches),
    path("/me/pt-slots", class_views.my_pt_slots),
    path("/me/pt-sessions", class_views.book_pt),
    path("/me/pt-sessions/<int:session_id>/cancel", class_views.cancel_my_pt),
    path("/<int:member_id>/billing", billing_views.member_billing),
    path("/<int:member_id>/payment-method", billing_views.member_payment_method),
    path("/<int:member_id>/renewal-quote", billing_views.member_renewal_quote),
    path("/<int:member_id>/payments", billing_views.member_payment),
    path("/<int:member_id>/cancel", views.member_cancel),
    path("/<int:member_id>/access-card", views.member_access_card),
    path("/<int:member_id>", views.member_detail),
    path("", views.member_list),
]
