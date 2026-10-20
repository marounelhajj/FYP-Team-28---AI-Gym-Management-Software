from django.contrib import admin
from .models import CheckIn, CheckInFlag


@admin.register(CheckIn)
class CheckInAdmin(admin.ModelAdmin):
    list_display = ("member", "result", "reason", "checked_in_at")
    list_filter = ("result",)
    search_fields = ("member__name", "member__email")


@admin.register(CheckInFlag)
class CheckInFlagAdmin(admin.ModelAdmin):
    list_display = ("check_in", "reason", "status", "flagged_by", "flagged_at", "resolved_by")
    list_filter = ("status", "reason")
    search_fields = ("check_in__member__name", "note")
