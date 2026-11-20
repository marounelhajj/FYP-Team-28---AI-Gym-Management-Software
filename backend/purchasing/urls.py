from django.urls import path

from . import views

urlpatterns = [
    path("/meta", views.meta),
    path("/orders", views.order_list),
    path("/approvals", views.approvals),
    path("/orders/<int:order_id>", views.order_detail),
    path("/orders/<int:order_id>/approve", views.approve),
    path("/orders/<int:order_id>/reject", views.reject),
    path("/orders/<int:order_id>/cancel", views.cancel),
    path("/orders/<int:order_id>/receive", views.receive),
    path("/orders/<int:order_id>/close", views.close_short),
    path("/orders/<int:order_id>/resend", views.resend),
    path("/suppliers", views.supplier_list),
    path("/suppliers/<int:supplier_id>", views.supplier_detail),
    path("/products/<int:product_id>/sourcing", views.product_sourcing),
]
