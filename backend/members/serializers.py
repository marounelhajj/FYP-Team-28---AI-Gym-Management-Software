from rest_framework import serializers
from .models import Member, Waiver


class WaiverSerializer(serializers.ModelSerializer):
    signatureName = serializers.CharField(source="signature_name")
    healthDisclaimerAccepted = serializers.BooleanField(source="health_disclaimer_accepted")
    liabilityWaiverAccepted = serializers.BooleanField(source="liability_waiver_accepted")
    signedAt = serializers.DateTimeField(source="signed_at", format="%Y-%m-%d %H:%M")

    class Meta:
        model = Waiver
        fields = ["signatureName", "healthDisclaimerAccepted", "liabilityWaiverAccepted", "signedAt"]


class MemberSerializer(serializers.ModelSerializer):
    membershipPlan = serializers.CharField(source="membership_plan")
    joinDate = serializers.DateField(source="join_date", format="%Y-%m-%d")
    # null for members who predate this feature (the seeded demo data) or
    # were otherwise never put through the signup flow.
    waiver = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = ["id", "name", "email", "phone", "status", "branch", "membershipPlan", "joinDate", "waiver"]

    def get_waiver(self, obj):
        try:
            waiver = obj.waiver
        except Waiver.DoesNotExist:
            return None
        return WaiverSerializer(waiver).data


# Used by POST /api/members to register a new walk-in member.
#
# User story: "As a receptionist, I want to register a new walk-in member's
# profile and membership plan, so that I can onboard new customers on the
# spot."
#
# status and joinDate are intentionally NOT accepted from the client: a
# freshly registered walk-in is always Active, and the join date is always
# "today" - both are set server-side in create() below.
#
# Also handles the signup waiver/health disclaimer:
# "As a member, I want to sign a digital waiver and health disclaimer
# during signup, so that the gym has liability protection on file before
# I start training."
#
# signatureName, healthDisclaimerAccepted, and liabilityWaiverAccepted are
# all required - registration fails (no Member row is created at all) if
# either acknowledgment is missing or false.
class MemberCreateSerializer(serializers.ModelSerializer):
    membershipPlan = serializers.ChoiceField(source="membership_plan", choices=Member.Plan.choices)
    signatureName = serializers.CharField(source="signature_name", max_length=150)
    healthDisclaimerAccepted = serializers.BooleanField(source="health_disclaimer_accepted")
    liabilityWaiverAccepted = serializers.BooleanField(source="liability_waiver_accepted")

    class Meta:
        model = Member
        fields = [
            "name",
            "email",
            "phone",
            "branch",
            "membershipPlan",
            "signatureName",
            "healthDisclaimerAccepted",
            "liabilityWaiverAccepted",
        ]

    def validate_healthDisclaimerAccepted(self, value):
        if not value:
            raise serializers.ValidationError(
                "You must acknowledge the health disclaimer to complete registration."
            )
        return value

    def validate_liabilityWaiverAccepted(self, value):
        if not value:
            raise serializers.ValidationError(
                "You must agree to the liability waiver to complete registration."
            )
        return value

    def create(self, validated_data):
        from django.db import transaction
        from django.utils import timezone

        signature_name = validated_data.pop("signature_name")
        health_disclaimer_accepted = validated_data.pop("health_disclaimer_accepted")
        liability_waiver_accepted = validated_data.pop("liability_waiver_accepted")

        validated_data["status"] = Member.Status.ACTIVE
        validated_data["join_date"] = timezone.now().date()

        with transaction.atomic():
            member = Member.objects.create(**validated_data)
            Waiver.objects.create(
                member=member,
                signature_name=signature_name,
                health_disclaimer_accepted=health_disclaimer_accepted,
                liability_waiver_accepted=liability_waiver_accepted,
            )

        return Member.objects.select_related("waiver").get(pk=member.pk)
