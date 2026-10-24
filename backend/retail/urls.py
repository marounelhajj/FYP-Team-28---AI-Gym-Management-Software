from django.urls import path

from . import views

urlpatterns = [
    path("/meta", views.retail_meta),
    path("/member", views.member_lookup),
    path("/products", views.product_list),
    path("/products/<int:product_id>/stock", views.product_stock),
    path("/products/<int:product_id>", views.product_detail),
    path("/sales", views.sale_list),
    path("/sales/<int:sale_id>/void", views.void_sale),
]
