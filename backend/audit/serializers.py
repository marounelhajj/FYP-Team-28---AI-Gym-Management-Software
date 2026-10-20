from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    createdAt = serializers.DateTimeField(source="created_at")
    actionLabel = serializers.CharField(source="get_action_display")
    actorType = serializers.CharField(source="actor_type")
    actorName = serializers.CharField(source="actor_name")
    actorUsername = serializers.CharField(source="actor_username")
    actorRole = serializers.CharField(source="actor_role")
    targetType = serializers.CharField(source="target_type")
    targetId = serializers.CharField(source="target_id")
    targetLabel = serializers.CharField(source="target_label")
    ipAddress = serializers.CharField(source="ip_address", allow_null=True)

    class Meta:
        model = AuditLog
        fields = [
            "id", "createdAt", "action", "actionLabel", "actorType", "actorName", "actorUsername", "actorRole",
            "targetType", "targetId", "targetLabel", "branch", "summary", "details", "ipAddress",
        ]
