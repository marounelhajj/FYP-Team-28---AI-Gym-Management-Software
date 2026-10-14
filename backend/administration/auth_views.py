import time
from datetime import timedelta

import segno
from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import totp
from .models import StaffAccount, StaffBackupCode
from .permissions import authorize
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
#
# Two steps (SCRUM-87): a correct password only marks the session as
# "pending" for that account. The staff session itself ("staff_account_id")
# is issued by /auth/2fa/verify once a code from the authenticator app (or a
# backup code) checks out. An account that hasn't enrolled yet gets its QR
# code in the login response and confirms enrollment through the same
# verify endpoint.

PENDING_ACCOUNT_KEY = "pending_staff_account_id"
PENDING_STARTED_KEY = "pending_staff_started_at"
PENDING_TTL_SECONDS = 5 * 60

MAX_FAILED_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=5)


def _session_payload(account):
    data = StaffAccountSerializer(account).data
    data["permissions"] = account.role.permissions
    return data


def _enrollment_payload(account, secret):
    uri = totp.provisioning_uri(secret, account.username)
    return {
        "secret": secret,
        "otpauthUri": uri,
        "qrCode": segno.make(uri, error="m").svg_data_uri(scale=5, border=2),
    }


def _pending_account(request):
    account_id = request.session.get(PENDING_ACCOUNT_KEY)
    started = request.session.get(PENDING_STARTED_KEY) or 0
    if not account_id or time.time() - started > PENDING_TTL_SECONDS:
        return None
    return StaffAccount.objects.select_related("role").filter(id=account_id, is_active=True).first()


def _clear_pending(request):
    request.session.pop(PENDING_ACCOUNT_KEY, None)
    request.session.pop(PENDING_STARTED_KEY, None)


def _locked_response(account):
    minutes = max(1, -(-int((account.two_factor_locked_until - timezone.now()).total_seconds()) // 60))
    return Response(
        {"error": f"Too many incorrect codes. Try again in {minutes} minute{'s' if minutes != 1 else ''}."},
        status=429,
    )


def _is_locked(account):
    return account.two_factor_locked_until is not None and account.two_factor_locked_until > timezone.now()


def _use_backup_code(account, code):
    match = account.backup_codes.filter(code_hash=totp.hash_backup_code(code), used_at__isnull=True).first()
    if match is None:
        return False
    match.used_at = timezone.now()
    match.save(update_fields=["used_at"])
    return True


# POST /api/auth/login
# Body: { username, password }
# 200 + {"twoFactor": "verify"} when the account has 2FA set up, or
#       {"twoFactor": "enroll", "enrollment": {secret, otpauthUri, qrCode}}
#       when it still has to scan a QR code. Either way the next call is
#       POST /api/auth/2fa/verify - no staff session exists yet.
# 401 + {"error": ...} on bad credentials or a deactivated account.
# 429 while the account is locked out after repeated wrong codes.
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

    if _is_locked(account):
        return _locked_response(account)

    request.session.pop("member_id", None)
    request.session.pop("staff_account_id", None)
    request.session[PENDING_ACCOUNT_KEY] = account.id
    request.session[PENDING_STARTED_KEY] = time.time()

    if account.two_factor_enabled:
        return Response({"twoFactor": "verify"})

    # Not enrolled yet (new account, or an administrator reset it). Keep the
    # secret from an earlier unfinished attempt so a QR code that was
    # already scanned stays valid.
    secret = totp.decrypt_secret(account.totp_secret_encrypted) if account.totp_secret_encrypted else None
    if not secret:
        secret = totp.generate_secret()
        account.totp_secret_encrypted = totp.encrypt_secret(secret)
        account.save(update_fields=["totp_secret_encrypted"])
    return Response({"twoFactor": "enroll", "enrollment": _enrollment_payload(account, secret)})


# POST /api/auth/2fa/verify
# Body: { code } - a 6-digit authenticator code, or a backup code
#         (backup codes only once enrollment is complete).
# 200 + account/session payload; right after enrollment the payload also
#       carries "backupCodes", which are never shown again.
# 401 when there is no pending sign-in (or it expired) or the code is wrong.
# 429 after MAX_FAILED_ATTEMPTS wrong codes, for LOCKOUT.
@api_view(["POST"])
def verify_two_factor(request):
    account = _pending_account(request)
    if account is None:
        _clear_pending(request)
        return Response({"error": "Your sign-in has expired. Enter your password again."}, status=401)

    with transaction.atomic():
        account = StaffAccount.objects.select_for_update().select_related("role").get(id=account.id)
        if _is_locked(account):
            return _locked_response(account)

        code = request.data.get("code") or ""
        secret = totp.decrypt_secret(account.totp_secret_encrypted) if account.totp_secret_encrypted else None
        step = totp.verify(secret, code, last_used_step=account.totp_last_used_step) if secret else None
        enrolling = not account.two_factor_enabled

        if step is None and (enrolling or not _use_backup_code(account, code)):
            account.failed_2fa_attempts += 1
            if account.failed_2fa_attempts >= MAX_FAILED_ATTEMPTS:
                account.failed_2fa_attempts = 0
                account.two_factor_locked_until = timezone.now() + LOCKOUT
                account.save(update_fields=["failed_2fa_attempts", "two_factor_locked_until"])
                return _locked_response(account)
            account.save(update_fields=["failed_2fa_attempts"])
            return Response({"error": "Invalid code."}, status=401)

        if step is not None:
            account.totp_last_used_step = step
        account.failed_2fa_attempts = 0
        account.two_factor_locked_until = None

        backup_codes = None
        if enrolling:
            account.two_factor_enabled = True
            backup_codes = totp.generate_backup_codes()
            account.backup_codes.all().delete()
            StaffBackupCode.objects.bulk_create(
                StaffBackupCode(account=account, code_hash=totp.hash_backup_code(c)) for c in backup_codes
            )
        account.save()

    _clear_pending(request)
    # New session key now that the account is fully authenticated, so a
    # session id seen before sign-in can't be reused afterwards.
    request.session.cycle_key()
    request.session["staff_account_id"] = account.id

    data = _session_payload(account)
    if backup_codes:
        data["backupCodes"] = backup_codes
    return Response(data)


# POST /api/staff/<id>/2fa/reset
# For a staff member who lost their phone. Wipes the secret and backup
# codes; the account enrolls again on its next login, and any session it
# already has stops working until it does (see permissions.get_staff_account).
@api_view(["POST"])
def reset_two_factor(request, staff_id):
    _, denied = authorize(request, "manage_staff_accounts")
    if denied:
        return denied

    try:
        account = StaffAccount.objects.select_related("role").get(id=staff_id)
    except StaffAccount.DoesNotExist:
        return Response({"error": f"Staff account {staff_id} not found"}, status=404)

    with transaction.atomic():
        account.totp_secret_encrypted = ""
        account.two_factor_enabled = False
        account.totp_last_used_step = None
        account.failed_2fa_attempts = 0
        account.two_factor_locked_until = None
        account.save()
        account.backup_codes.all().delete()
    return Response(StaffAccountSerializer(account).data)


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

    if not account.two_factor_enabled:
        request.session.flush()
        return Response({"error": "Two-factor sign-in has been reset. Log in again."}, status=401)

    return Response(_session_payload(account))
