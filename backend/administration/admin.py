from django.contrib import admin
from .models import Role, StaffAccount


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)


@admin.register(StaffAccount)
class StaffAccountAdmin(admin.ModelAdmin):
    list_display = ("full_name", "username", "email", "job_title", "role", "is_active")
    list_filter = ("job_title", "role", "is_active")
    search_fields = ("full_name", "email", "username")
