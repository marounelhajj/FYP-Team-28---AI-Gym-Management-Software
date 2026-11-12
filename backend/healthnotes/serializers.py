from datetime import date

from django.utils import timezone
from rest_framework import serializers

from .models import HealthNote

OLDEST_SINCE = date(1930, 1, 1)


def _choice(choices, message):
    return {"choices": choices, "error_messages": {"invalid_choice": message, "required": message}}


# The member's own note: what they send and what they get back.
class HealthNoteSerializer(serializers.ModelSerializer):
    kind = serializers.ChoiceField(**_choice(HealthNote.Kind.choices, "Pick what kind of note this is."))
    bodyArea = serializers.ChoiceField(
        source="body_area", required=False, **_choice(HealthNote.BodyArea.choices, "Pick the body area from the list."),
    )
    severity = serializers.ChoiceField(**_choice(HealthNote.Severity.choices, "Say how much it limits your training."))
    title = serializers.CharField(max_length=80, trim_whitespace=True)
    details = serializers.CharField(max_length=500, required=False, allow_blank=True, trim_whitespace=True)
    since = serializers.DateField(required=False, allow_null=True)
    status = serializers.ChoiceField(required=False, **_choice(HealthNote.Status.choices, "Status is Active or Resolved."))
    resolvedOn = serializers.DateField(source="resolved_on", read_only=True)
    updatedAt = serializers.SerializerMethodField()

    class Meta:
        model = HealthNote
        fields = ["id", "kind", "bodyArea", "severity", "title", "details", "since", "status", "resolvedOn", "updatedAt"]

    def get_updatedAt(self, obj):
        return timezone.localtime(obj.updated_at).strftime("%Y-%m-%d")

    def validate_title(self, value):
        value = " ".join(value.split())
        if len(value) < 3:
            raise serializers.ValidationError("Say what it is in a few words, e.g. \"Lower back pain\".")
        return value

    def validate_since(self, value):
        if value is None:
            return value
        if value > timezone.localdate():
            raise serializers.ValidationError("That date is in the future.")
        if value < OLDEST_SINCE:
            raise serializers.ValidationError("That date is too far back.")
        return value
