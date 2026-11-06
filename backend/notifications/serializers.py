from rest_framework import serializers

from .models import NotificationSettings


def _choice(choices, source, message):
    return serializers.ChoiceField(choices=choices, source=source, error_messages={"invalid_choice": message})


# PUT/PATCH /api/members/me/reminders - any of these, each optional.
class NotificationSettingsSerializer(serializers.Serializer):
    classDayBefore = serializers.BooleanField(source="class_day_before")
    classMinutesBefore = _choice(
        NotificationSettings.CLASS_MINUTES_CHOICES, "class_minutes_before",
        "Pick off (0), 30, 60, 120 or 180 minutes.",
    )
    renewalDaysBefore = _choice(
        NotificationSettings.RENEWAL_DAYS_CHOICES, "renewal_days_before", "Pick off (0), 1, 3, 7 or 14 days.",
    )
    email = serializers.BooleanField()
