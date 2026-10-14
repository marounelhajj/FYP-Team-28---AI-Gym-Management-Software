from rest_framework.response import Response

from .models import StaffAccount

# Server-side enforcement of role permissions.
#
# The frontend hides screens a role can't use, but that is only a courtesy:
# anyone can call the API directly, so every staff-only endpoint checks the
# caller's permissions here. Permissions are read from the database on every
# request (not copied into the session at login), so changing a role in the
# Admin Console, or deactivating an account, takes effect immediately.
#
# 401 = no valid staff session (not logged in, deactivated, or a member
#       session, which never carries staff permissions).
# 403 = logged in, but the role doesn't grant any of the required keys.


def get_staff_account(request):
    account_id = request.session.get("staff_account_id")
    if not account_id:
        return None
    return StaffAccount.objects.select_related("role").filter(id=account_id, is_active=True).first()


# Returns (account, None) when the caller holds at least one of
# `permissions`, otherwise (None, error_response) - the view should return
# the response as-is.
def authorize(request, *permissions):
    account = get_staff_account(request)
    if account is None:
        return None, Response({"error": "Not authenticated."}, status=401)

    granted = set(account.role.permissions)
    if not granted.intersection(permissions):
        return None, Response({"error": "You don't have permission to do that."}, status=403)
    return account, None
