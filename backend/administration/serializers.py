from rest_framework import serializers

from .models import PERMISSION_KEYS, Role, StaffAccount


class RoleSerializer(serializers.ModelSerializer):
    staffCount = serializers.IntegerField(source="staff_accounts.count", read_only=True)

    class Meta:
        model = Role
        fields = ["id", "name", "description", "permissions", "staffCount"]


# Used by POST /api/roles and PUT /api/roles/<id>.
#
# User story: "As a system administrator, I want to define roles with
# specific permission sets, so that access matches each job function."
class RoleWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["name", "description", "permissions"]

    def validate_permissions(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("permissions must be a list of permission keys.")
        invalid = sorted(set(value) - PERMISSION_KEYS)
        if invalid:
            raise serializers.ValidationError(f"Unknown permission(s): {', '.join(invalid)}")
        return value


class StaffAccountSerializer(serializers.ModelSerializer):
    fullName = serializers.CharField(source="full_name")
    jobTitle = serializers.CharField(source="job_title")
    roleId = serializers.IntegerField(source="role_id")
    roleName = serializers.CharField(source="role.name", read_only=True)
    isActive = serializers.BooleanField(source="is_active")
    createdAt = serializers.DateTimeField(source="created_at", format="%Y-%m-%d", read_only=True)

    class Meta:
        model = StaffAccount
        fields = [
            "id", "fullName", "email", "username", "jobTitle",
            "roleId", "roleName", "isActive", "createdAt",
        ]


# Used by POST /api/staff to create a new staff login account.
#
# User story: "As a system administrator, I want to create, edit and
# deactivate staff login accounts, so that only current staff can sign in
# to the system."
#
# A new account is always created active - deactivation is a separate,
# explicit action (PATCH isActive: false), never implicit at creation.
class StaffAccountCreateSerializer(serializers.ModelSerializer):
    fullName = serializers.CharField(source="full_name")
    jobTitle = serializers.ChoiceField(source="job_title", choices=StaffAccount.JobTitle.choices)
    roleId = serializers.PrimaryKeyRelatedField(source="role", queryset=Role.objects.all())
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = StaffAccount
        fields = ["fullName", "email", "username", "jobTitle", "roleId", "password"]

    def create(self, validated_data):
        password = validated_data.pop("password")
        account = StaffAccount(**validated_data, is_active=True)
        account.set_password(password)
        account.save()
        return account


# Used by PATCH /api/staff/<id> for both editing profile fields and
# deactivating/reactivating an account (isActive: false / true). Password
# is optional - only reset it when explicitly provided.
class StaffAccountUpdateSerializer(serializers.ModelSerializer):
    fullName = serializers.CharField(source="full_name", required=False)
    jobTitle = serializers.ChoiceField(source="job_title", choices=StaffAccount.JobTitle.choices, required=False)
    roleId = serializers.PrimaryKeyRelatedField(source="role", queryset=Role.objects.all(), required=False)
    isActive = serializers.BooleanField(source="is_active", required=False)
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = StaffAccount
        fields = ["fullName", "email", "username", "jobTitle", "roleId", "isActive", "password"]

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
