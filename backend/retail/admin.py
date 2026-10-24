from django.contrib import admin
from .models import BranchStock, Product, Sale, SaleItem


class BranchStockInline(admin.TabularInline):
    model = BranchStock
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("name",)
    inlines = [BranchStockInline]


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    readonly_fields = ("product", "product_name", "unit_price", "quantity", "line_total")


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("id", "sold_at", "branch", "total", "payment_method", "member", "sold_by", "voided_at")
    list_filter = ("branch", "payment_method")
    inlines = [SaleItemInline]
