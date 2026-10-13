from django.contrib import admin
from .models import CheckIn


@admin.register(CheckIn)
class CheckInAdmin(admin.ModelAdmin):
    list_display = ("member", "result", "reason", "checked_in_at")
    list_filter = ("result",)
    search_fields = ("member__name", "member__email")
