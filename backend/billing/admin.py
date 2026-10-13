from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("member", "amount", "method", "paid_at")
    list_filter = ("method",)
    search_fields = ("member__name", "member__email")
