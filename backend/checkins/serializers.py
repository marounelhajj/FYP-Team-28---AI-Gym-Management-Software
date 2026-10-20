from rest_framework import serializers

from members import qr
from .models import CheckIn, CheckInFlag

# Denials that often mean someone else is using the membership - shown to the
# front desk as "worth reviewing", so they can flag the attempt.
SUSPICIOUS_DENIALS = {
    "Already checked in": "Already inside right now - someone may be sharing this membership.",
    "Replaced card": "A replaced card was used - it may be lost, stolen or shared.",
}
DATETIME = "%Y-%m-%d %H:%M"


class CheckInFlagSerializer(serializers.ModelSerializer):
    flaggedBy = serializers.CharField(source="flagged_by.full_name", default=None)
    flaggedAt = serializers.DateTimeField(source="flagged_at", format=DATETIME)
    resolvedBy = serializers.CharField(source="resolved_by.full_name", default=None)
    resolvedAt = serializers.DateTimeField(source="resolved_at", format=DATETIME, allow_null=True)
    resolutionNote = serializers.CharField(source="resolution_note")

    class Meta:
        model = CheckInFlag
        fields = ["id", "reason", "note", "status", "flaggedBy", "flaggedAt", "resolvedBy", "resolvedAt", "resolutionNote"]


class CheckInSerializer(serializers.ModelSerializer):
    memberId = serializers.IntegerField(source="member_id", read_only=True)
    memberName = serializers.CharField(source="member.name", read_only=True)
    checkedInAt = serializers.DateTimeField(source="checked_in_at", format=DATETIME)
    checkedOutAt = serializers.DateTimeField(source="checked_out_at", format=DATETIME, allow_null=True)
    duration = serializers.SerializerMethodField()
    suspicion = serializers.SerializerMethodField()
    flag = serializers.SerializerMethodField()

    class Meta:
        model = CheckIn
        fields = [
            "id", "memberId", "memberName", "result", "reason", "checkedInAt", "checkedOutAt", "duration",
            "suspicion", "flag",
        ]

    def get_suspicion(self, obj):
        return SUSPICIOUS_DENIALS.get(obj.reason) if obj.result == CheckIn.Result.DENIED else None

    def get_flag(self, obj):
        flag = getattr(obj, "flag", None)
        return CheckInFlagSerializer(flag).data if flag else None

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


# A flag with the attempt it's about, for the "Flagged attempts" list.
class FlaggedAttemptSerializer(CheckInFlagSerializer):
    checkIn = CheckInSerializer(source="check_in")
    memberStatus = serializers.CharField(source="check_in.member.status")

    class Meta(CheckInFlagSerializer.Meta):
        fields = CheckInFlagSerializer.Meta.fields + ["checkIn", "memberStatus"]


# POST /api/checkins/<id>/flag
class CheckInFlagCreateSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=CheckInFlag.Reason.choices)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        attrs["note"] = " ".join(attrs.get("note", "").split())
        if attrs["reason"] == CheckInFlag.Reason.OTHER and not attrs["note"]:
            raise serializers.ValidationError({"note": ["Say what looked suspicious."]})
        return attrs


# POST /api/checkins/flags/<id>/resolve
class CheckInFlagResolveSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=[CheckInFlag.Status.CONFIRMED, CheckInFlag.Status.DISMISSED])
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    def validate_note(self, value):
        return " ".join(value.split())
