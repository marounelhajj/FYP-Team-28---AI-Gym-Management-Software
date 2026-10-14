from django.contrib import admin
from .models import Member, Waiver


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "branch", "status", "membership_plan", "join_date")
    list_filter = ("branch", "status", "membership_plan")
    search_fields = ("name", "email")


@admin.register(Waiver)
class WaiverAdmin(admin.ModelAdmin):
    list_display = ("member", "signature_name", "signed_via", "waiver_version", "signed_at")
    list_filter = ("signed_via", "waiver_version")
    search_fields = ("member__name", "signature_name")
