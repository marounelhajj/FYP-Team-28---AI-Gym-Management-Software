from django.contrib import admin

from .models import CoachFeedback


@admin.register(CoachFeedback)
class CoachFeedbackAdmin(admin.ModelAdmin):
    list_display = ("session_name", "session_starts_at", "coach", "member", "rating", "created_at")
    list_filter = ("rating", "branch")
    search_fields = ("session_name", "coach__full_name", "member__name", "comment")
