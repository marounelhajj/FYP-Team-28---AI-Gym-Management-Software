from rest_framework import serializers

from members.models import Member

from .models import AREAS, Complaint


def _area():
    return serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=5)


# POST /api/members/me/branch-feedback/surveys
class SurveySerializer(serializers.Serializer):
    branch = serializers.ChoiceField(choices=Member.Branch.choices)
    nps = serializers.IntegerField(min_value=0, max_value=10, error_messages={
        "required": "How likely are you to recommend this branch? Pick 0 to 10.",
        "min_value": "Pick 0 to 10.", "max_value": "Pick 0 to 10.",
    })
    cleanliness = _area()
    equipment = _area()
    staff = _area()
    classes = _area()
    atmosphere = _area()
    comment = serializers.CharField(max_length=1000, required=False, allow_blank=True, trim_whitespace=True)
    anonymous = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if all(attrs.get(key) is None for key, _ in AREAS) and not attrs.get("comment"):
            # NPS alone says how they feel, not why - ask for at least one more thing.
            raise serializers.ValidationError("Rate at least one area or leave a comment, so the branch knows why.")
        return attrs


# POST /api/members/me/complaints
class ComplaintSerializer(serializers.Serializer):
    branch = serializers.ChoiceField(choices=Member.Branch.choices)
    category = serializers.ChoiceField(choices=Complaint.Category.choices)
    subject = serializers.CharField(max_length=120, trim_whitespace=True)
    description = serializers.CharField(max_length=2000, trim_whitespace=True)

    def validate_subject(self, value):
        value = " ".join(value.split())
        if len(value) < 5:
            raise serializers.ValidationError("Sum it up in a few words, e.g. \"Treadmill 3 is broken\".")
        return value

    def validate_description(self, value):
        if len(value) < 15:
            raise serializers.ValidationError("Tell us a bit more - what happened, where and when.")
        return value


class MessageSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=1000, trim_whitespace=True)
    internal = serializers.BooleanField(required=False, default=False)


# PATCH /api/branch-feedback/complaints/<id> - a status change, optionally with a reply.
class StatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Complaint.Status.choices)
    message = serializers.CharField(max_length=1000, required=False, allow_blank=True, trim_whitespace=True)
