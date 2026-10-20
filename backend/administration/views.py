from rest_framework.decorators import api_view
from rest_framework.response import Response

from audit.log import changes, record
from audit.models import AuditLog

from .models import PERMISSION_CHOICES, Role, StaffAccount
from .permissions import authorize
from .serializers import (
    RoleSerializer,
    RoleWriteSerializer,
    StaffAccountCreateSerializer,
    StaffAccountSerializer,
    StaffAccountUpdateSerializer,
)


# GET  /api/staff  - list staff login accounts (optionally filter/search)
# POST /api/staff  - create a new staff login account
#
# GET query params (all optional, all combinable):
#   q         - case-insensitive substring match on full name
#   roleId    - exact match on role id
#   branch    - exact match: Hamra | Achrafieh | Jnah | Zalka
#   isActive  - "true" | "false"
#
# User story (both GET and POST/PATCH below): "As a system administrator, I
# want to create, edit and deactivate staff login accounts, so that only
# current staff can sign in to the system."
#
# The branch field and branch filter also serve: "As a general manager, I
# want to add, edit, and remove staff and trainer profiles at a branch, so
# that I can manage headcount and certified training staff."
@api_view(["GET", "POST"])
def staff_list(request):
    admin, denied = authorize(request, "manage_staff_accounts")
    if denied:
        return denied

    if request.method == "POST":
        serializer = StaffAccountCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        account = serializer.save()
        data = StaffAccountSerializer(account).data
        record(
            request, AuditLog.Action.STAFF_CREATED, actor=admin, target=account,
            summary=f"Created staff account {account.username} ({account.role.name})",
            details={k: data[k] for k in ("fullName", "email", "username", "jobTitle", "roleName", "branch")},
        )
        return Response(data, status=201)

    queryset = StaffAccount.objects.select_related("role").all()

    q = request.query_params.get("q")
    if q and q.strip():
        queryset = queryset.filter(full_name__icontains=q.strip())

    role_id = request.query_params.get("roleId")
    if role_id:
        queryset = queryset.filter(role_id=role_id)

    branch = request.query_params.get("branch")
    if branch:
        queryset = queryset.filter(branch=branch)

    active_param = request.query_params.get("isActive")
    if active_param is not None:
        queryset = queryset.filter(is_active=active_param.lower() == "true")

    serialized = StaffAccountSerializer(queryset, many=True).data
    return Response({"total": len(serialized), "results": serialized})


# GET   /api/staff/<id>  - fetch one staff account
# PATCH /api/staff/<id>  - edit profile fields and/or set isActive to
#                          deactivate/reactivate the account
@api_view(["GET", "PATCH"])
def staff_detail(request, staff_id):
    admin, denied = authorize(request, "manage_staff_accounts")
    if denied:
        return denied

    try:
        account = StaffAccount.objects.get(id=staff_id)
    except StaffAccount.DoesNotExist:
        return Response({"error": f"Staff account {staff_id} not found"}, status=404)

    if request.method == "PATCH":
        serializer = StaffAccountUpdateSerializer(account, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        before = StaffAccountSerializer(account).data
        account = serializer.save()
        after = StaffAccountSerializer(account).data
        _record_staff_update(request, admin, account, before, after, bool(serializer.validated_data.get("password")))
        return Response(after)

    return Response(StaffAccountSerializer(account).data)


def _record_staff_update(request, admin, account, before, after, password_changed):
    changed = changes(before, after, ignore=("roleId",))
    if not changed and not password_changed:
        return
    details = {"changes": changed}
    if password_changed:
        details["passwordReset"] = True

    if "isActive" in changed:
        action = AuditLog.Action.STAFF_REACTIVATED if account.is_active else AuditLog.Action.STAFF_DEACTIVATED
        summary = f"{'Reactivated' if account.is_active else 'Deactivated'} staff account {account.username}"
    else:
        action = AuditLog.Action.STAFF_UPDATED
        what = sorted(changed) + (["password"] if password_changed else [])
        summary = f"Edited staff account {account.username} ({', '.join(what)})"
    record(request, action, actor=admin, target=account, summary=summary, details=details)


def _permission_changes(before, after):
    return {"added": sorted(set(after) - set(before)), "removed": sorted(set(before) - set(after))}


# GET  /api/roles  - list roles with their permission sets
# POST /api/roles  - define a new role
#
# User story: "As a system administrator, I want to define roles with
# specific permission sets, so that access matches each job function."
@api_view(["GET", "POST"])
def role_list(request):
    # Listing roles is also needed by the staff-account form's role picker,
    # so either admin permission may read; only manage_roles may write.
    if request.method == "POST":
        admin, denied = authorize(request, "manage_roles")
    else:
        admin, denied = authorize(request, "manage_roles", "manage_staff_accounts")
    if denied:
        return denied

    if request.method == "POST":
        serializer = RoleWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        role = serializer.save()
        record(
            request, AuditLog.Action.ROLE_CREATED, actor=admin, target=role, branch="",
            summary=f"Created role {role.name}", details={"permissions": sorted(role.permissions)},
        )
        return Response(RoleSerializer(role).data, status=201)

    roles = Role.objects.all()
    return Response(RoleSerializer(roles, many=True).data)


# GET /api/roles/<id>  - fetch one role
# PUT /api/roles/<id>  - edit name/description/permission set
@api_view(["GET", "PUT"])
def role_detail(request, role_id):
    if request.method == "PUT":
        admin, denied = authorize(request, "manage_roles")
    else:
        admin, denied = authorize(request, "manage_roles", "manage_staff_accounts")
    if denied:
        return denied

    try:
        role = Role.objects.get(id=role_id)
    except Role.DoesNotExist:
        return Response({"error": f"Role {role_id} not found"}, status=404)

    if request.method == "PUT":
        serializer = RoleWriteSerializer(role, data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        before = {"name": role.name, "description": role.description, "permissions": list(role.permissions)}
        role = serializer.save()
        changed = changes(before, {"name": role.name, "description": role.description})
        permissions = _permission_changes(before["permissions"], role.permissions)
        if permissions["added"] or permissions["removed"]:
            changed["permissions"] = permissions
        if changed:
            record(
                request, AuditLog.Action.ROLE_UPDATED, actor=admin, target=role, branch="",
                summary=f"Edited role {role.name} ({', '.join(sorted(changed))})", details={"changes": changed},
            )
        return Response(RoleSerializer(role).data)

    return Response(RoleSerializer(role).data)


# GET /api/permissions
# Returns every permission key the system knows about, so the "define
# roles" UI can render its checkbox list without hardcoding a set that can
# drift out of sync with the backend.
@api_view(["GET"])
def permission_list(request):
    _, denied = authorize(request, "manage_roles")
    if denied:
        return denied
    return Response([{"key": key, "label": label} for key, label in PERMISSION_CHOICES])
