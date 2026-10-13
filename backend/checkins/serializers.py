from rest_framework import serializers
from .models import CheckIn


class CheckInSerializer(serializers.ModelSerializer):
    memberId = serializers.IntegerField(source="member_id", read_only=True)
    memberName = serializers.CharField(source="member.name", read_only=True)
    checkedInAt = serializers.DateTimeField(source="checked_in_at", format="%Y-%m-%d %H:%M")
    checkedOutAt = serializers.DateTimeField(
        source="checked_out_at", format="%Y-%m-%d %H:%M", allow_null=True
    )
    duration = serializers.SerializerMethodField()

    class Meta:
        model = CheckIn
        fields = ["id", "memberId", "memberName", "result", "reason", "checkedInAt", "checkedOutAt", "duration"]

    # "Xh Ym" (or just "Ym" under an hour) between check-in and check-out -
    # null until checked out.
    def get_duration(self, obj):
        if not obj.checked_out_at:
            return None
        total_minutes = int((obj.checked_out_at - obj.checked_in_at).total_seconds() // 60)
        hours, minutes = divmod(max(total_minutes, 0), 60)
        return f"{hours}h {minutes}m" if hours else f"{minutes}m"


# Used by POST /api/checkins. Just the ID typed in (or, in the future,
# decoded from a scanned QR code) - everything else (who the member is,
# whether to allow them in) is resolved server-side in the view.
class CheckInCreateSerializer(serializers.Serializer):
    membershipId = serializers.IntegerField(min_value=1)
