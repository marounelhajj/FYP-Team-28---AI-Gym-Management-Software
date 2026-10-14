import base64
import time
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from members.models import Member

from . import totp
from .models import Role, StaffAccount
from .testing import staff_login

PASSWORD = "ChangeMe123!"


def make_account(username, role_name, permissions, is_active=True):
    role, _ = Role.objects.get_or_create(name=role_name, defaults={"permissions": permissions})
    account = StaffAccount(
        full_name=username.title(),
        email=f"{username}@gym.com",
        username=username,
        job_title=StaffAccount.JobTitle.RECEPTIONIST,
        role=role,
        is_active=is_active,
    )
    account.set_password(PASSWORD)
    account.save()
    return account


# User story (SCRUM-117): "As a staff member, I want the system to block pages
# and actions outside my role's permissions, so that sensitive data stays
# restricted."
class RolePermissionEnforcementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_account("admin", "System Administrator", ["manage_staff_accounts", "manage_roles", "manage_members"])
        make_account("recep", "Receptionist", ["manage_members"])
        make_account("mkt", "Marketing Staff", ["manage_marketing_campaigns"])
        make_account("rolesonly", "Roles Only", ["manage_roles"])
        make_account("gone", "Receptionist", ["manage_members"], is_active=False)

    def login(self, username):
        res = staff_login(self.client, username, PASSWORD)
        self.assertEqual(res.status_code, 200, res.content)

    # --- not logged in -> 401 on every protected endpoint ---
    def test_anonymous_requests_are_rejected(self):
        for path in ["/api/staff", "/api/staff/1", "/api/roles", "/api/roles/1", "/api/permissions", "/api/members"]:
            self.assertEqual(self.client.get(path).status_code, 401, path)
        self.assertEqual(self.client.post("/api/members", {}, content_type="application/json").status_code, 401)
        self.assertEqual(self.client.post("/api/roles", {}, content_type="application/json").status_code, 401)

    # --- logged in, wrong role -> 403 ---
    def test_receptionist_cannot_touch_admin_endpoints(self):
        self.login("recep")
        for path in ["/api/staff", "/api/roles", "/api/permissions"]:
            self.assertEqual(self.client.get(path).status_code, 403, path)
        res = self.client.post("/api/roles", {"name": "X", "permissions": []}, content_type="application/json")
        self.assertEqual(res.status_code, 403)
        res = self.client.patch("/api/staff/1", {"isActive": False}, content_type="application/json")
        self.assertEqual(res.status_code, 403)

    def test_receptionist_can_use_member_directory(self):
        self.login("recep")
        self.assertEqual(self.client.get("/api/members").status_code, 200)

    def test_marketing_staff_cannot_read_member_directory(self):
        self.login("mkt")
        self.assertEqual(self.client.get("/api/members").status_code, 403)
        res = self.client.post("/api/members", {"name": "A"}, content_type="application/json")
        self.assertEqual(res.status_code, 403)

    def test_roles_can_be_read_with_either_admin_permission_but_written_only_with_manage_roles(self):
        self.login("admin")
        self.assertEqual(self.client.get("/api/roles").status_code, 200)
        self.client.post("/api/auth/logout")
        self.login("rolesonly")
        self.assertEqual(self.client.get("/api/roles").status_code, 200)
        self.assertEqual(self.client.get("/api/staff").status_code, 403)

    def test_admin_keeps_access(self):
        self.login("admin")
        for path in ["/api/staff", "/api/roles", "/api/permissions", "/api/members"]:
            self.assertEqual(self.client.get(path).status_code, 200, path)

    # --- permissions are checked live, not frozen at login ---
    def test_permission_change_applies_to_existing_session(self):
        self.login("recep")
        self.assertEqual(self.client.get("/api/members").status_code, 200)
        Role.objects.filter(name="Receptionist").update(permissions=[])
        self.assertEqual(self.client.get("/api/members").status_code, 403)

    def test_deactivated_account_loses_access_immediately(self):
        self.login("recep")
        StaffAccount.objects.filter(username="recep").update(is_active=False)
        self.assertEqual(self.client.get("/api/members").status_code, 401)

    def test_member_session_is_not_staff(self):
        session = self.client.session
        session["member_id"] = 1
        session.save()
        self.assertEqual(self.client.get("/api/members").status_code, 401)
        self.assertEqual(self.client.get("/api/staff").status_code, 401)

    # --- public endpoints stay public ---
    def test_public_endpoints_still_open(self):
        self.assertEqual(self.client.get("/api/members/meta").status_code, 200)
        self.assertEqual(self.client.get("/api/plans").status_code, 200)
        self.assertEqual(self.client.get("/api/health").status_code, 200)


# User story (SCRUM-87): "As a system administrator, I want staff accounts to
# require two-factor authentication, so that unauthorized people can't access
# sensitive gym data."
class StaffTwoFactorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_account("admin", "System Administrator", ["manage_staff_accounts", "manage_members"])
        cls.recep = make_account("recep", "Receptionist", ["manage_members"])

    def password_step(self, username="recep"):
        return self.client.post("/api/auth/login", {"username": username, "password": PASSWORD}, content_type="application/json")

    def verify(self, code):
        return self.client.post("/api/auth/2fa/verify", {"code": code}, content_type="application/json")

    def enroll(self, username="recep"):
        res = self.password_step(username)
        secret = res.json()["enrollment"]["secret"]
        res = self.verify(totp.code_at(secret))
        self.assertEqual(res.status_code, 200, res.content)
        self.client.post("/api/auth/logout")
        return secret, res.json()["backupCodes"]

    # Next unused code for an enrolled account (each step works only once).
    def fresh_code(self, secret, username="recep"):
        last = StaffAccount.objects.get(username=username).totp_last_used_step
        return totp.code_at_step(secret, max(totp.current_step(), (last or 0) + 1))

    def reset_recep_as_admin(self):
        staff_login(self.client, "admin", PASSWORD)
        res = self.client.post(f"/api/staff/{self.recep.id}/2fa/reset")
        self.client.post("/api/auth/logout")
        return res

    # --- enrollment ---
    def test_first_login_requires_enrollment_and_issues_no_session(self):
        res = self.password_step()
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["twoFactor"], "enroll")
        self.assertTrue(body["enrollment"]["otpauthUri"].startswith("otpauth://totp/"))
        self.assertTrue(body["enrollment"]["qrCode"].startswith("data:image/svg+xml"))
        self.assertNotIn("id", body)
        self.assertEqual(self.client.get("/api/members").status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_enrollment_confirms_with_code_and_returns_backup_codes_once(self):
        res = self.password_step()
        secret = res.json()["enrollment"]["secret"]
        res = self.verify(totp.code_at(secret))
        self.assertEqual(res.status_code, 200)
        backup_codes = res.json()["backupCodes"]
        self.assertEqual(len(backup_codes), totp.BACKUP_CODE_COUNT)
        self.assertEqual(self.client.get("/api/members").status_code, 200)

        account = StaffAccount.objects.get(username="recep")
        self.assertTrue(account.two_factor_enabled)
        self.assertNotIn(secret, account.totp_secret_encrypted)
        stored = set(account.backup_codes.values_list("code_hash", flat=True))
        self.assertEqual(stored, {totp.hash_backup_code(c) for c in backup_codes})
        self.assertFalse(stored & set(backup_codes))

    def test_unfinished_enrollment_keeps_the_same_secret(self):
        first = self.password_step().json()["enrollment"]["secret"]
        second = self.password_step().json()["enrollment"]["secret"]
        self.assertEqual(first, second)

    def test_secret_is_never_returned_after_enrollment(self):
        secret, _ = self.enroll()
        res = self.password_step()
        self.assertEqual(res.json(), {"twoFactor": "verify"})
        res = self.verify(self.fresh_code(secret))
        self.assertNotIn(secret, res.content.decode())
        self.client.post("/api/auth/logout")
        staff_login(self.client, "admin", PASSWORD)
        for path in ["/api/staff", f"/api/staff/{self.recep.id}"]:
            self.assertNotIn(secret, self.client.get(path).content.decode())

    # --- signing in ---
    def test_login_with_valid_code(self):
        secret, _ = self.enroll()
        self.password_step()
        res = self.verify(self.fresh_code(secret))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["username"], "recep")
        self.assertNotIn("backupCodes", res.json())
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)

    def test_wrong_code_is_rejected(self):
        secret, _ = self.enroll()
        self.password_step()
        wrong = str((int(self.fresh_code(secret)) + 1) % 10 ** 6).zfill(6)
        res = self.verify(wrong)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["error"], "Invalid code.")
        self.assertEqual(self.client.get("/api/members").status_code, 401)

    def test_expired_code_is_rejected(self):
        secret, _ = self.enroll()
        self.password_step()
        res = self.verify(totp.code_at(secret, now=time.time() - 5 * totp.STEP_SECONDS))
        self.assertEqual(res.status_code, 401)

    def test_used_code_cannot_be_replayed(self):
        secret, _ = self.enroll()
        self.password_step()
        code = self.fresh_code(secret)
        self.assertEqual(self.verify(code).status_code, 200)
        self.client.post("/api/auth/logout")
        self.password_step()
        self.assertEqual(self.verify(code).status_code, 401)

    def test_verify_without_password_step_is_rejected(self):
        secret, _ = self.enroll()
        self.assertEqual(self.verify(self.fresh_code(secret)).status_code, 401)

    def test_pending_sign_in_expires(self):
        secret, _ = self.enroll()
        self.password_step()
        session = self.client.session
        session["pending_staff_started_at"] = time.time() - 10 * 60
        session.save()
        self.assertEqual(self.verify(self.fresh_code(secret)).status_code, 401)

    # --- backup codes ---
    def test_backup_code_works_once(self):
        _, backup_codes = self.enroll()
        self.password_step()
        self.assertEqual(self.verify(backup_codes[0].lower()).status_code, 200)
        self.client.post("/api/auth/logout")
        self.password_step()
        self.assertEqual(self.verify(backup_codes[0]).status_code, 401)
        self.assertEqual(self.verify(backup_codes[1]).status_code, 200)

    # --- rate limit ---
    def test_repeated_wrong_codes_lock_the_account(self):
        secret, _ = self.enroll()
        self.password_step()
        for _ in range(4):
            self.assertEqual(self.verify("000000").status_code, 401)
        self.assertEqual(self.verify("000000").status_code, 429)
        # Even the right code is refused during the lockout, and so is a new
        # password attempt.
        self.assertEqual(self.verify(self.fresh_code(secret)).status_code, 429)
        self.assertEqual(self.password_step().status_code, 429)

    def test_lockout_ends(self):
        secret, _ = self.enroll()
        StaffAccount.objects.filter(username="recep").update(
            two_factor_locked_until=timezone.now() - timedelta(seconds=1)
        )
        self.password_step()
        self.assertEqual(self.verify(self.fresh_code(secret)).status_code, 200)

    # --- administrator reset ---
    def test_admin_reset_forces_re_enrollment(self):
        secret, backup_codes = self.enroll()
        res = self.reset_recep_as_admin()
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["twoFactorEnabled"])

        res = self.password_step()
        self.assertEqual(res.json()["twoFactor"], "enroll")
        self.assertNotEqual(res.json()["enrollment"]["secret"], secret)
        # Old backup codes are gone, and backup codes can't stand in for
        # confirming a new enrollment anyway.
        self.assertEqual(self.verify(backup_codes[0]).status_code, 401)

    def test_reset_ends_existing_sessions(self):
        staff_login(self.client, "recep", PASSWORD)
        self.assertEqual(self.client.get("/api/members").status_code, 200)
        StaffAccount.objects.filter(username="recep").update(two_factor_enabled=False)
        self.assertEqual(self.client.get("/api/members").status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_only_staff_admins_can_reset(self):
        staff_login(self.client, "recep", PASSWORD)
        self.assertEqual(self.client.post(f"/api/staff/{self.admin.id}/2fa/reset").status_code, 403)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.post(f"/api/staff/{self.admin.id}/2fa/reset").status_code, 401)

    # --- members are not affected ---
    def test_member_login_has_no_second_factor(self):
        member = Member(
            name="Mia Member", email="mia@example.com", phone="70123456", branch="Hamra",
            join_date=date.today(), username="mia",
        )
        member.set_password(PASSWORD)
        member.save()
        res = self.client.post("/api/members/login", {"username": "mia", "password": PASSWORD}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertNotIn("twoFactor", res.json())
        self.assertEqual(self.client.get("/api/members/me").status_code, 200)


class TotpTests(TestCase):
    # RFC 6238 appendix B test vectors (SHA-1, secret "12345678901234567890").
    def test_rfc_6238_vectors(self):
        secret = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(totp.code_at(secret, now=59), "287082")
        self.assertEqual(totp.code_at(secret, now=1111111109), "081804")

    def test_neighbouring_steps_are_accepted(self):
        secret = totp.generate_secret()
        now = 1_000_000
        for offset in (-30, 0, 30):
            self.assertIsNotNone(totp.verify(secret, totp.code_at(secret, now=now + offset), now=now))
        self.assertIsNone(totp.verify(secret, totp.code_at(secret, now=now + 60), now=now))

    def test_secret_round_trips_through_encryption(self):
        secret = totp.generate_secret()
        token = totp.encrypt_secret(secret)
        self.assertNotIn(secret, token)
        self.assertEqual(totp.decrypt_secret(token), secret)
        self.assertIsNone(totp.decrypt_secret("not-a-token"))
