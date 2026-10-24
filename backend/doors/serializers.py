from rest_framework import serializers

from members.models import Member

from .models import Door


class DoorSerializer(serializers.ModelSerializer):
    isActive = serializers.BooleanField(source="is_active")
    createdBy = serializers.CharField(source="created_by.full_name", default=None)
    createdAt = serializers.DateTimeField(source="created_at", format="%Y-%m-%d %H:%M")
    lastSeenAt = serializers.DateTimeField(source="last_seen_at", format="%Y-%m-%d %H:%M", allow_null=True)

    class Meta:
        model = Door
        fields = ["id", "name", "branch", "kind", "isActive", "createdBy", "createdAt", "lastSeenAt"]


# POST /api/doors (all fields) and PATCH /api/doors/<id> (any of them).
class DoorWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    branch = serializers.ChoiceField(choices=Member.Branch.choices)
    kind = serializers.ChoiceField(choices=Door.Kind.choices)
    isActive = serializers.BooleanField(required=False)

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Give the door a name, e.g. Main entrance.")
        return value


class DoorScanSerializer(serializers.Serializer):
    qrCode = serializers.CharField(allow_blank=True)
