from django.contrib import admin
from .models import TrainingEvent


# Read-only: events are written by the app itself, never by hand.
@admin.register(TrainingEvent)
class TrainingEventAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "event_type", "member_id", "branch", "trainer", "session_id")
    list_filter = ("event_type", "branch")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
