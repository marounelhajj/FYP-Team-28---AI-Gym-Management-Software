from rest_framework import serializers

from members import qr
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


# Used by POST /api/checkins and /api/checkins/checkout. Either the
# membership ID typed in, or the payload of the member's check-in QR code
# (scanned by camera, or typed by a USB scanner) - see members/qr.py.
# Everything else (who the member is, whether to allow them in) is
# resolved server-side in the view. validated_data always ends up with
# membershipId, plus cardNumber when a QR code was scanned.
class CheckInCreateSerializer(serializers.Serializer):
    membershipId = serializers.IntegerField(min_value=1, required=False)
    qrCode = serializers.CharField(required=False)

    def validate(self, attrs):
        if "qrCode" in attrs:
            card = qr.read(attrs.pop("qrCode"))
            if card is None:
                raise serializers.ValidationError(
                    {"qrCode": ["This QR code isn't a valid Fitness Factory membership code."]}
                )
            attrs["membershipId"], attrs["cardNumber"] = card
        if "membershipId" not in attrs:
            raise serializers.ValidationError({"membershipId": ["Enter a membership ID or scan a QR code."]})
        return attrs
