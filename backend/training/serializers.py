from rest_framework import serializers

from .models import TrainingEvent


class TrainingEventSerializer(serializers.ModelSerializer):
    eventType = serializers.CharField(source="event_type")
    occurredAt = serializers.DateTimeField(source="occurred_at")
    memberId = serializers.IntegerField(source="member_id")
    trainerId = serializers.IntegerField(source="trainer_id", allow_null=True)
    sessionId = serializers.CharField(source="session_id")

    class Meta:
        model = TrainingEvent
        fields = ["id", "eventType", "occurredAt", "memberId", "branch", "trainerId", "sessionId", "payload"]
