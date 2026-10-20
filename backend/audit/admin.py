from django.contrib import admin
from .models import AuditLog


# Read-only: entries are written by the app itself, never by hand.
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor_username", "actor_role", "target_label", "branch", "summary")
    list_filter = ("action", "actor_type", "branch")
    search_fields = ("actor_name", "actor_username", "target_label", "summary")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
