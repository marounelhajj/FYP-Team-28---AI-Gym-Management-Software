from datetime import timezone as dt_timezone

from rest_framework import serializers

from .models import TrainingEvent


class TrainingEventSerializer(serializers.ModelSerializer):
    eventType = serializers.CharField(source="event_type")
    # Always UTC ("...Z") for the training dataset, whatever the server's TIME_ZONE.
    occurredAt = serializers.DateTimeField(source="occurred_at", default_timezone=dt_timezone.utc)
    memberId = serializers.IntegerField(source="member_id")
    trainerId = serializers.IntegerField(source="trainer_id", allow_null=True)
    sessionId = serializers.CharField(source="session_id")

    class Meta:
        model = TrainingEvent
        fields = ["id", "eventType", "occurredAt", "memberId", "branch", "trainerId", "sessionId", "payload"]
