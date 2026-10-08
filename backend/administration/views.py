from rest_framework.decorators import api_view
from rest_framework.response import Response

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
#   isActive  - "true" | "false"
#
# User story (both GET and POST/PATCH below): "As a system administrator, I
# want to create, edit and deactivate staff login accounts, so that only
# current staff can sign in to the system."
@api_view(["GET", "POST"])
def staff_list(request):
    _, denied = authorize(request, "manage_staff_accounts")
    if denied:
        return denied

    if request.method == "POST":
        serializer = StaffAccountCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        account = serializer.save()
        return Response(StaffAccountSerializer(account).data, status=201)

    queryset = StaffAccount.objects.select_related("role").all()

    q = request.query_params.get("q")
    if q and q.strip():
        queryset = queryset.filter(full_name__icontains=q.strip())

    role_id = request.query_params.get("roleId")
    if role_id:
        queryset = queryset.filter(role_id=role_id)

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
    _, denied = authorize(request, "manage_staff_accounts")
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
        account = serializer.save()
        return Response(StaffAccountSerializer(account).data)

    return Response(StaffAccountSerializer(account).data)


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
        _, denied = authorize(request, "manage_roles")
    else:
        _, denied = authorize(request, "manage_roles", "manage_staff_accounts")
    if denied:
        return denied

    if request.method == "POST":
        serializer = RoleWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        role = serializer.save()
        return Response(RoleSerializer(role).data, status=201)

    roles = Role.objects.all()
    return Response(RoleSerializer(roles, many=True).data)


# GET /api/roles/<id>  - fetch one role
# PUT /api/roles/<id>  - edit name/description/permission set
@api_view(["GET", "PUT"])
def role_detail(request, role_id):
    if request.method == "PUT":
        _, denied = authorize(request, "manage_roles")
    else:
        _, denied = authorize(request, "manage_roles", "manage_staff_accounts")
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
        role = serializer.save()
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
