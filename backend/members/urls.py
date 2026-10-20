from django.urls import path

from billing import views as billing_views

from . import auth_views, views

urlpatterns = [
    path("/meta", views.member_meta),
    path("/waiver", views.waiver_text),
    path("/signup", auth_views.signup),
    path("/login", auth_views.login),
    path("/logout", auth_views.logout),
    path("/me", auth_views.me),
    path("/me/qr", auth_views.my_qr),
    path("/me/payment-method", billing_views.my_payment_method),
    path("/me/billing", billing_views.my_billing),
    path("/me/freeze", views.my_freeze),
    path("/me/resume", views.my_resume),
    path("/me/cancel", views.my_cancel),
    path("/<int:member_id>/billing", billing_views.member_billing),
    path("/<int:member_id>/payment-method", billing_views.member_payment_method),
    path("/<int:member_id>/renewal-quote", billing_views.member_renewal_quote),
    path("/<int:member_id>/payments", billing_views.member_payment),
    path("/<int:member_id>/cancel", views.member_cancel),
    path("/<int:member_id>/access-card", views.member_access_card),
    path("/<int:member_id>", views.member_detail),
    path("", views.member_list),
]
