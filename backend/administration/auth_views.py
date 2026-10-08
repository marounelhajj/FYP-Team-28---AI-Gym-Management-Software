from django.contrib.auth.hashers import check_password
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import StaffAccount
from .serializers import StaffAccountSerializer

# Staff sign-in. Deliberately NOT self-service and there is no role picker:
# a staff account's role is assigned once, server-side, by a System
# Administrator when the account is created (see StaffAccountCreateSerializer
# in serializers.py). Login only ever proves "which already-provisioned
# account are you" - it never lets the client declare or change a role.
#
# Session-based: on success we store the account id in the Django session
# (request.session), which sets a cookie the browser sends automatically on
# later requests. No token to manage on the frontend.


def _session_payload(account):
    data = StaffAccountSerializer(account).data
    data["permissions"] = account.role.permissions
    return data


# POST /api/auth/login
# Body: { username, password }
# 200 + account/session payload on success.
# 401 + {"error": ...} on bad credentials or a deactivated account.
@api_view(["POST"])
def login(request):
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""

    try:
        account = StaffAccount.objects.select_related("role").get(username=username)
    except StaffAccount.DoesNotExist:
        return Response({"error": "Invalid username or password."}, status=401)

    if not check_password(password, account.password_hash):
        return Response({"error": "Invalid username or password."}, status=401)

    if not account.is_active:
        return Response(
            {"error": "This account has been deactivated. Contact your system administrator."},
            status=401,
        )

    request.session.pop("member_id", None)
    request.session["staff_account_id"] = account.id
    return Response(_session_payload(account))


# POST /api/auth/logout
@api_view(["POST"])
def logout(request):
    request.session.flush()
    return Response({"ok": True})


# GET /api/auth/me
# Lets the frontend check "is there already a logged-in session" (e.g. on
# page load / refresh) without asking for credentials again.
# 200 + account/session payload if logged in, 401 otherwise.
@api_view(["GET"])
def me(request):
    account_id = request.session.get("staff_account_id")
    if not account_id:
        return Response({"error": "Not authenticated."}, status=401)

    try:
        account = StaffAccount.objects.select_related("role").get(id=account_id)
    except StaffAccount.DoesNotExist:
        request.session.flush()
        return Response({"error": "Not authenticated."}, status=401)

    if not account.is_active:
        request.session.flush()
        return Response({"error": "This account has been deactivated."}, status=401)

    return Response(_session_payload(account))
