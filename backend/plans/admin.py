from django.contrib import admin
from .models import BranchPromotion, MembershipPlan


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "billing_cycle", "max_promo_discount_percent", "is_active", "updated_at")
    list_filter = ("billing_cycle", "is_active")
    search_fields = ("name",)


@admin.register(BranchPromotion)
class BranchPromotionAdmin(admin.ModelAdmin):
    list_display = ("name", "plan", "branch", "discount_type", "discount_value", "start_date", "end_date", "is_active")
    list_filter = ("branch", "discount_type", "is_active")
    search_fields = ("name", "plan__name")
