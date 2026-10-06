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


# Used by POST /api/members/signup for self-service registration.
#
# User story: "As a prospective member, I want to browse membership plans
# and sign up online, so that I can join a branch without visiting in
# person first."
#
# Unlike a walk-in (MemberCreateSerializer above), a self-signup member
# sets their own username/password here and can log in immediately -
# that's the whole point of self-service.
class MemberSignupSerializer(serializers.ModelSerializer):
    membershipPlan = serializers.ChoiceField(source="membership_plan", choices=Member.Plan.choices)
    password = serializers.CharField(write_only=True, min_length=8)
    # validators=[] disables DRF's auto-generated UniqueValidator (attached
    # because username is unique=True on the model) so our own
    # validate_username message below is the one that actually fires.
    username = serializers.CharField(validators=[])

    class Meta:
        model = Member
        fields = ["name", "email", "phone", "branch", "membershipPlan", "username", "password"]

    def validate_username(self, value):
        if Member.objects.filter(username=value).exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate_email(self, value):
        if Member.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def create(self, validated_data):
        from django.utils import timezone

        password = validated_data.pop("password")
        validated_data["status"] = Member.Status.ACTIVE
        validated_data["join_date"] = timezone.now().date()
        member = Member(**validated_data)
        member.set_password(password)
        member.save()
        return member
