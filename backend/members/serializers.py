from rest_framework import serializers
from .models import Member


class MemberSerializer(serializers.ModelSerializer):
    membershipPlan = serializers.CharField(source="membership_plan")
    joinDate = serializers.DateField(source="join_date", format="%Y-%m-%d")

    class Meta:
        model = Member
        fields = ["id", "name", "email", "phone", "status", "branch", "membershipPlan", "joinDate"]


# Used by POST /api/members to register a new walk-in member.
#
# User story: "As a receptionist, I want to register a new walk-in member's
# profile and membership plan, so that I can onboard new customers on the
# spot."
#
# status and joinDate are intentionally NOT accepted from the client: a
# freshly registered walk-in is always Active, and the join date is always
# "today" - both are set server-side in create() below.
class MemberCreateSerializer(serializers.ModelSerializer):
    membershipPlan = serializers.ChoiceField(source="membership_plan", choices=Member.Plan.choices)

    class Meta:
        model = Member
        fields = ["name", "email", "phone", "branch", "membershipPlan"]

    def create(self, validated_data):
        from django.utils import timezone

        validated_data["status"] = Member.Status.ACTIVE
        validated_data["join_date"] = timezone.now().date()
        return Member.objects.create(**validated_data)
