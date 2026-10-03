from django.contrib import admin
from .models import Member


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "branch", "status", "membership_plan", "join_date")
    list_filter = ("branch", "status", "membership_plan")
    search_fields = ("name", "email")
