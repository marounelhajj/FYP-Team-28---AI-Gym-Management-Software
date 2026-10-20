from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from members.models import Member
from plans.models import MembershipPlan

from .models import AuditLog, AuditLogImmutable

PASSWORD = "ChangeMe123!"
SIGNED_WAIVER = {"liabilityWaiverAccepted": True, "healthDisclaimerAccepted": True}
JSON = "application/json"


def _staff(username, full_name, permissions, branch=None, role_name=None):
    role = Role.objects.create(name=role_name or f"{username} role", permissions=permissions)
    account = StaffAccount(
        full_name=full_name, email=f"{username}@gym.com", username=username,
        job_title=StaffAccount.JobTitle.RECEPTIONIST, role=role, branch=branch,
    )
    account.set_password(PASSWORD)
    account.save()
    return account


# User story (SCRUM-124): "As a system administrator, I want sensitive
# actions to be written to an audit log automatically, so that there is a
# permanent record of who did what."
class AuditLogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.basic = MembershipPlan.objects.create(name="Basic", price="35.00")
        cls.admin = _staff("admin", "Maya Admin", ["manage_staff_accounts", "manage_roles"], role_name="System Administrator")
        cls.gm = _staff("gm", "Rami GM", ["manage_membership_plans"], role_name="General Manager")
        cls.desk = _staff("desk", "Dana Desk", ["manage_members"], branch="Hamra", role_name="Receptionist")
        today = timezone.localdate()
        cls.member = Member.objects.create(
            name="Lea Haddad", email="lea@example.com", phone="1", branch="Jnah", join_date=today,
            membership_plan="Basic", subscription_expires_at=today + timedelta(days=10),
            username="lea",
        )
        cls.member.set_password(PASSWORD)
        cls.member.save()

    def latest(self, action):
        return AuditLog.objects.filter(action=action).first()

    # --- who did it, copied onto the entry ---
    def test_staff_action_records_actor_target_and_branch(self):
        staff_login(self.client, "desk", PASSWORD)
        res = self.client.post(f"/api/members/{self.member.id}/cancel")
        self.assertEqual(res.status_code, 200)

        entry = self.latest(AuditLog.Action.MEMBER_CANCELLED)
        self.assertEqual(entry.actor_type, AuditLog.ActorType.STAFF)
        self.assertEqual(entry.actor_staff, self.desk)
        self.assertEqual((entry.actor_name, entry.actor_username, entry.actor_role), ("Dana Desk", "desk", "Receptionist"))
        self.assertEqual((entry.target_type, entry.target_id, entry.target_label), ("member", str(self.member.id), "Lea Haddad"))
        # The branch the action concerns (the member's), not the receptionist's.
        self.assertEqual(entry.branch, "Jnah")
        self.assertEqual(entry.details, {"previousStatus": "Active"})
        self.assertEqual(entry.ip_address, "127.0.0.1")

    def test_entry_keeps_actor_snapshot_after_account_changes(self):
        staff_login(self.client, "desk", PASSWORD)
        self.client.post(f"/api/members/{self.member.id}/cancel")
        self.desk.full_name = "Dana Renamed"
        self.desk.is_active = False
        self.desk.save()

        entry = self.latest(AuditLog.Action.MEMBER_CANCELLED)
        self.assertEqual(entry.actor_name, "Dana Desk")

    # --- staff sign-in ---
    def test_successful_staff_login_is_logged(self):
        res = staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(res.status_code, 200)
        entry = self.latest(AuditLog.Action.STAFF_LOGIN)
        self.assertEqual(entry.actor_staff, self.desk)
        self.assertEqual(entry.details, {"method": "enrolled two-factor"})

    def test_failed_logins_are_logged_with_reason(self):
        self.client.post("/api/auth/login", {"username": "nobody", "password": "x"}, content_type=JSON)
        self.client.post("/api/auth/login", {"username": "desk", "password": "wrong"}, content_type=JSON)

        unknown, wrong = AuditLog.objects.filter(action=AuditLog.Action.STAFF_LOGIN_FAILED).order_by("id")
        self.assertEqual(unknown.actor_type, AuditLog.ActorType.ANONYMOUS)
        self.assertEqual(unknown.actor_username, "nobody")
        self.assertEqual(unknown.details, {"reason": "unknown username"})
        self.assertEqual(wrong.target_id, str(self.desk.id))
        self.assertEqual(wrong.details, {"reason": "wrong password"})
        # The attempted password is never written anywhere.
        self.assertNotIn("wrong", wrong.summary.replace("wrong password", ""))

    def test_wrong_two_factor_codes_and_lockout_are_logged(self):
        staff_login(self.client, "desk", PASSWORD)  # enroll
        self.client.post("/api/auth/logout")
        self.client.post("/api/auth/login", {"username": "desk", "password": PASSWORD}, content_type=JSON)
        for _ in range(5):
            self.client.post("/api/auth/2fa/verify", {"code": "000000"}, content_type=JSON)

        failed = AuditLog.objects.filter(action=AuditLog.Action.STAFF_LOGIN_FAILED, details__reason="wrong two-factor code")
        self.assertEqual(failed.count(), 4)
        self.assertIsNotNone(self.latest(AuditLog.Action.STAFF_2FA_LOCKED))

    # --- staff accounts and roles ---
    def test_staff_account_changes_are_logged(self):
        staff_login(self.client, "admin", PASSWORD)
        res = self.client.post("/api/staff", {
            "fullName": "New Coach", "email": "coach@gym.com", "username": "coach", "jobTitle": "Coach",
            "roleId": self.desk.role_id, "branch": "Zalka", "password": "Password123!",
        }, content_type=JSON)
        self.assertEqual(res.status_code, 201, res.content)
        created = self.latest(AuditLog.Action.STAFF_CREATED)
        self.assertEqual(created.actor_staff, self.admin)
        self.assertEqual(created.branch, "Zalka")
        self.assertNotIn("password", created.details)

        coach_id = res.json()["id"]
        self.client.patch(f"/api/staff/{coach_id}", {"branch": "Hamra", "password": "Another123!"}, content_type=JSON)
        edited = self.latest(AuditLog.Action.STAFF_UPDATED)
        self.assertEqual(edited.details, {"changes": {"branch": ["Zalka", "Hamra"]}, "passwordReset": True})
        self.assertNotIn("Another123!", str(edited.details) + edited.summary)

        self.client.patch(f"/api/staff/{coach_id}", {"isActive": False}, content_type=JSON)
        self.assertIsNotNone(self.latest(AuditLog.Action.STAFF_DEACTIVATED))

        # Saving with nothing changed doesn't add noise.
        count = AuditLog.objects.count()
        self.client.patch(f"/api/staff/{coach_id}", {"branch": "Hamra"}, content_type=JSON)
        self.assertEqual(AuditLog.objects.count(), count)

    def test_role_permission_changes_are_logged(self):
        staff_login(self.client, "admin", PASSWORD)
        role = self.desk.role
        self.client.put(f"/api/roles/{role.id}", {
            "name": role.name, "description": "", "permissions": ["manage_members", "manage_billing"],
        }, content_type=JSON)
        entry = self.latest(AuditLog.Action.ROLE_UPDATED)
        self.assertEqual(entry.details["changes"]["permissions"], {"added": ["manage_billing"], "removed": []})

    def test_two_factor_reset_is_logged(self):
        staff_login(self.client, "desk", PASSWORD)
        self.client.post("/api/auth/logout")
        staff_login(self.client, "admin", PASSWORD)
        self.client.post(f"/api/staff/{self.desk.id}/2fa/reset")
        entry = self.latest(AuditLog.Action.STAFF_2FA_RESET)
        self.assertEqual((entry.actor_staff, entry.target_id), (self.admin, str(self.desk.id)))

    # --- plans ---
    def test_plan_price_change_is_logged_with_old_and_new(self):
        staff_login(self.client, "gm", PASSWORD)
        self.client.patch(f"/api/plans/{self.basic.id}", {"price": "40.00"}, content_type=JSON)
        entry = self.latest(AuditLog.Action.PLAN_UPDATED)
        self.assertEqual(entry.details, {"changes": {"price": ["35.00", "40.00"]}})
        self.assertEqual(entry.actor_role, "General Manager")

    def test_promotion_creation_is_logged_for_its_branch(self):
        staff_login(self.client, "gm", PASSWORD)
        today = timezone.localdate()
        res = self.client.post("/api/plans/promotions", {
            "planId": self.basic.id, "branch": "Achrafieh", "name": "Spring", "discountType": "Percent",
            "discountValue": "10.00", "startDate": str(today), "endDate": str(today + timedelta(days=7)),
        }, content_type=JSON)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(self.latest(AuditLog.Action.PROMOTION_CREATED).branch, "Achrafieh")

    # --- members, billing, access cards ---
    def test_renewal_and_payment_method_change_are_logged(self):
        staff_login(self.client, "desk", PASSWORD)
        self.client.put(f"/api/members/{self.member.id}/payment-method", {
            "method": "Card", "cardHolderName": "Lea Haddad", "cardLast4": "4242",
            "cardExpiryMonth": 8, "cardExpiryYear": timezone.localdate().year + 2,
        }, content_type=JSON)
        method = self.latest(AuditLog.Action.PAYMENT_METHOD_UPDATED)
        self.assertEqual(method.details["changes"]["paymentMethod"][0], None)
        self.assertTrue(method.details["changes"]["paymentMethod"][1].startswith("Card ending 4242"))

        res = self.client.post(f"/api/members/{self.member.id}/payments", {
            "membershipPlan": "Basic", "method": "Cash", "duration": "1 Month",
        }, content_type=JSON)
        self.assertEqual(res.status_code, 201, res.content)
        payment = self.latest(AuditLog.Action.PAYMENT_RECORDED)
        self.assertEqual((payment.details["type"], payment.details["amount"]), ("Renewal", "35.00"))

    def test_walk_in_registration_and_card_reissue_are_logged(self):
        staff_login(self.client, "desk", PASSWORD)
        res = self.client.post("/api/members", {
            "name": "Sami Khoury", "email": "sami@example.com", "phone": "2", "branch": "Hamra",
            "membershipPlan": "Basic", "paymentMethod": "Cash", "paymentDuration": "1 Month",
            **SIGNED_WAIVER, "signatureName": "Sami Khoury",
        }, content_type=JSON)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(self.latest(AuditLog.Action.MEMBER_REGISTERED).target_label, "Sami Khoury")

        res = self.client.post(f"/api/members/{self.member.id}/access-card", {
            "reason": "Lost", "identityConfirmed": True,
        }, content_type=JSON)
        self.assertEqual(res.status_code, 201, res.content)
        reissue = self.latest(AuditLog.Action.ACCESS_CARD_REISSUED)
        self.assertEqual((reissue.details["cardNumber"], reissue.details["reason"]), (2, "Lost"))

    def test_member_self_service_actions_are_logged_with_member_as_actor(self):
        self.client.post("/api/members/login", {"username": "lea", "password": PASSWORD}, content_type=JSON)
        self.client.patch("/api/members/me", {"phone": "70999999"}, content_type=JSON)
        self.client.post("/api/members/me/freeze")
        self.client.post("/api/members/me/cancel")

        profile = self.latest(AuditLog.Action.MEMBER_PROFILE_UPDATED)
        self.assertEqual(profile.actor_type, AuditLog.ActorType.MEMBER)
        self.assertEqual(profile.actor_member, self.member)
        self.assertEqual(profile.details, {"changes": {"phone": ["1", "70999999"]}})
        self.assertIsNotNone(self.latest(AuditLog.Action.MEMBER_FROZEN))
        self.assertEqual(self.latest(AuditLog.Action.MEMBER_CANCELLED).details, {"previousStatus": "Frozen"})

    def test_online_signup_is_logged(self):
        res = self.client.post("/api/members/signup", {
            "name": "Rita Nassar", "email": "rita@example.com", "phone": "3", "branch": "Zalka",
            "membershipPlan": "Basic", "username": "rita", "password": "Password123!",
            "paymentMethod": "Cash", "paymentDuration": "1 Month", **SIGNED_WAIVER, "signatureName": "Rita Nassar",
        }, content_type=JSON)
        self.assertEqual(res.status_code, 201, res.content)
        entry = self.latest(AuditLog.Action.MEMBER_SIGNED_UP)
        self.assertEqual((entry.actor_username, entry.branch), ("rita", "Zalka"))

    # --- permanent ---
    def test_entries_cannot_be_edited_or_deleted(self):
        staff_login(self.client, "desk", PASSWORD)
        entry = self.latest(AuditLog.Action.STAFF_LOGIN)

        entry.summary = "nothing to see here"
        with self.assertRaises(AuditLogImmutable):
            entry.save()
        with self.assertRaises(AuditLogImmutable):
            entry.delete()
        with self.assertRaises(AuditLogImmutable):
            AuditLog.objects.all().delete()
        with self.assertRaises(AuditLogImmutable):
            AuditLog.objects.update(summary="x")
        self.assertEqual(AuditLog.objects.get(pk=entry.pk).summary, "desk signed in (enrolled two-factor)")

    def test_reads_are_not_logged(self):
        staff_login(self.client, "desk", PASSWORD)
        count = AuditLog.objects.count()
        self.client.get("/api/members")
        self.client.get(f"/api/members/{self.member.id}")
        self.assertEqual(AuditLog.objects.count(), count)


# User story (SCRUM-125): "As a general manager, I want to search and filter
# the audit log by user, action type, branch and date range, so that I can
# investigate a specific incident."
class AuditLogSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.gm = _staff("gm", "Rami GM", ["view_audit_log"], role_name="General Manager")
        _staff("desk", "Dana Desk", ["manage_members"], branch="Hamra", role_name="Receptionist")
        now = timezone.now()

        def entry(days_ago, action, username, branch="", summary="x"):
            return AuditLog.objects.create(
                created_at=now - timedelta(days=days_ago), action=action, actor_type=AuditLog.ActorType.STAFF,
                actor_username=username, actor_name=username.title(), actor_role="Receptionist",
                branch=branch, summary=summary,
            )

        cls.old_cancel = entry(10, AuditLog.Action.MEMBER_CANCELLED, "dsarkis", "Hamra")
        cls.reissue = entry(3, AuditLog.Action.ACCESS_CARD_REISSUED, "dsarkis", "Jnah")
        cls.signup = entry(2, AuditLog.Action.MEMBER_SIGNED_UP, "lea", "Zalka")
        cls.plan = entry(1, AuditLog.Action.PLAN_UPDATED, "rhaddad")
        cls.failed = entry(0, AuditLog.Action.STAFF_LOGIN_FAILED, "dsarkis")

    def setUp(self):
        staff_login(self.client, "gm", PASSWORD)

    def ids(self, query=""):
        res = self.client.get(f"/api/audit-log{query}")
        self.assertEqual(res.status_code, 200, res.content)
        # Filter out entries the logins above wrote themselves.
        return [r["id"] for r in res.json()["results"] if r["action"] != AuditLog.Action.STAFF_LOGIN]

    def test_newest_first(self):
        self.assertEqual(
            self.ids(), [self.failed.id, self.plan.id, self.signup.id, self.reissue.id, self.old_cancel.id],
        )

    def test_filter_by_user(self):
        self.assertEqual(self.ids("?user=DSARK"), [self.failed.id, self.reissue.id, self.old_cancel.id])
        self.assertEqual(self.ids("?user=Rhaddad"), [self.plan.id])  # name match too

    def test_filter_by_exact_action_or_category(self):
        self.assertEqual(self.ids("?action=member.cancelled"), [self.old_cancel.id])
        self.assertEqual(self.ids("?action=member"), [self.signup.id, self.old_cancel.id])

    def test_filter_by_branch(self):
        self.assertEqual(self.ids("?branch=Jnah"), [self.reissue.id])

    def test_filter_by_date_range_is_inclusive(self):
        today = timezone.localdate()
        since = today - timedelta(days=3)
        until = today - timedelta(days=1)
        self.assertEqual(self.ids(f"?dateFrom={since}&dateTo={until}"), [self.plan.id, self.signup.id, self.reissue.id])

    def test_filters_combine(self):
        since = timezone.localdate() - timedelta(days=5)
        self.assertEqual(self.ids(f"?user=dsarkis&branch=Jnah&dateFrom={since}"), [self.reissue.id])

    def test_invalid_filters_are_rejected(self):
        for query in ("?action=bogus", "?branch=Paris", "?dateFrom=yesterday", "?dateFrom=2026-10-10&dateTo=2026-10-01"):
            self.assertEqual(self.client.get(f"/api/audit-log{query}").status_code, 400, query)

    def test_pagination(self):
        res = self.client.get("/api/audit-log?limit=2&offset=1&action=member").json()
        self.assertEqual(res["total"], 2)
        self.assertEqual([r["id"] for r in res["results"]], [self.old_cancel.id])

    def test_meta_lists_actions_branches_and_users(self):
        meta = self.client.get("/api/audit-log/meta").json()
        groups = {g["value"]: g for g in meta["actionGroups"]}
        self.assertIn("member.cancelled", [a["value"] for a in groups["member"]["actions"]])
        self.assertEqual(meta["branches"], ["Hamra", "Achrafieh", "Jnah", "Zalka"])
        self.assertIn("dsarkis", [u["username"] for u in meta["users"]])

    def test_requires_view_audit_log(self):
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/audit-log").status_code, 401)
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.client.get("/api/audit-log").status_code, 403)
        self.assertEqual(self.client.get("/api/audit-log/meta").status_code, 403)
