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
# 401 = no valid staff session (not logged in, deactivated, two-factor
#       reset by an administrator, or a member session, which never
#       carries staff permissions).
# 403 = logged in, but the role doesn't grant any of the required keys.
#       Every 403 is written to the audit log as access.denied (SCRUM-117:
#       "blocked attempts are logged"), at most once a minute per account
#       and address so a screen retrying in a loop can't flood the log.

DENIAL_REPEAT_WINDOW_SECONDS = 60


def log_denied(request, account, permissions):
    from datetime import timedelta

    from django.utils import timezone

    from audit.log import record
    from audit.models import AuditLog

    path = request.path[:200]
    since = timezone.now() - timedelta(seconds=DENIAL_REPEAT_WINDOW_SECONDS)
    if AuditLog.objects.filter(
        action=AuditLog.Action.ACCESS_DENIED, actor_staff=account, created_at__gte=since,
        details__path=path, details__method=request.method,
    ).exists():
        return
    record(
        request, AuditLog.Action.ACCESS_DENIED, actor=account,
        summary=f"{account.full_name} was blocked from {request.method} {path}",
        details={"method": request.method, "path": path, "needs": sorted(permissions), "role": account.role.name},
    )


def get_staff_account(request):
    account_id = request.session.get("staff_account_id")
    if not account_id:
        return None
    return StaffAccount.objects.select_related("role").filter(id=account_id, is_active=True, two_factor_enabled=True).first()


# Returns (account, None) when the caller holds at least one of
# `permissions`, otherwise (None, error_response) - the view should return
# the response as-is.
def authorize(request, *permissions):
    account = get_staff_account(request)
    if account is None:
        return None, Response({"error": "Not authenticated."}, status=401)

    granted = set(account.role.permissions)
    if not granted.intersection(permissions):
        log_denied(request, account, permissions)
        return None, Response({"error": "You don't have permission to do that."}, status=403)
    return account, None
