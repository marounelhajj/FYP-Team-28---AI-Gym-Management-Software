from django.contrib import admin
from .models import AccessCardReissue, Member, Waiver


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "branch", "status", "membership_plan", "join_date", "access_card_number")
    list_filter = ("branch", "status", "membership_plan")
    search_fields = ("name", "email")


@admin.register(Waiver)
class WaiverAdmin(admin.ModelAdmin):
    list_display = ("member", "signature_name", "signed_via", "waiver_version", "signed_at")
    list_filter = ("signed_via", "waiver_version")
    search_fields = ("member__name", "signature_name")


@admin.register(AccessCardReissue)
class AccessCardReissueAdmin(admin.ModelAdmin):
    list_display = ("member", "card_number", "reason", "reissued_by", "reissued_at")
    list_filter = ("reason",)
    search_fields = ("member__name", "note")
