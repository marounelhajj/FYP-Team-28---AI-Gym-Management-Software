from django.contrib import admin
from .models import Door


@admin.register(Door)
class DoorAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "kind", "is_active", "last_seen_at")
    list_filter = ("branch", "kind", "is_active")
    exclude = ("key_hash",)
