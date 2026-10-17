from django.contrib import admin
from .models import Payment, PaymentMethod


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("member", "amount", "method", "method_detail", "paid_at", "recorded_by")
    list_filter = ("method",)
    search_fields = ("member__name", "member__email")


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("member", "method", "card_last4", "card_expiry_month", "card_expiry_year", "updated_at", "updated_by")
    list_filter = ("method",)
    search_fields = ("member__name", "member__email")
