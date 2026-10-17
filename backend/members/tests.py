from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from billing.models import Payment
from plans.models import MembershipPlan

from .models import Member, Waiver
from .waiver import WAIVER_VERSION

PASSWORD = "ChangeMe123!"
SIGNED_WAIVER = {"liabilityWaiverAccepted": True, "healthDisclaimerAccepted": True}


# User story (SCRUM-66): "As a prospective member, I want to browse
# membership plans and sign up online, so that I can join a branch without
# visiting in person first."
#
# Signup (and walk-in registration) must offer exactly the plans the
# General Manager currently sells - not a hard-coded list.
class SignupPlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MembershipPlan.objects.create(name="Basic", price="35.00")
        MembershipPlan.objects.create(name="Student Flex", price="25.00")
        MembershipPlan.objects.create(name="Legacy Gold", price="70.00", is_active=False)

    def signup(self, **overrides):
        payload = {
            "name": "Lea Haddad", "email": "lea@example.com", "phone": "70123456",
            "branch": "Hamra", "membershipPlan": "Student Flex",
            "username": "lea", "password": "Password123!",
            "paymentMethod": "Cash", "paymentDuration": "1 Month",
            **SIGNED_WAIVER, "signatureName": "Lea Haddad",
        }
        payload.update(overrides)
        return self.client.post("/api/members/signup", payload, content_type="application/json")

    def test_meta_lists_active_plans_cheapest_first(self):
        res = self.client.get("/api/members/meta")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["plans"], ["Student Flex", "Basic"])

    def test_plans_browsable_without_logging_in(self):
        res = self.client.get("/api/plans?isActive=true")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([p["name"] for p in res.json()["results"]], ["Student Flex", "Basic"])

        pricing = self.client.get("/api/plans/pricing?branch=Hamra")
        self.assertEqual(pricing.status_code, 200)

    def test_can_sign_up_to_a_gm_defined_plan(self):
        res = self.signup()
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["membershipPlan"], "Student Flex")
        self.assertEqual(res.json()["status"], "Active")

        # Logged straight in after signing up.
        me = self.client.get("/api/members/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["branch"], "Hamra")

    def test_plan_name_is_matched_case_insensitively_and_stored_canonically(self):
        res = self.signup(membershipPlan="  student flex ")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(Member.objects.get(username="lea").membership_plan, "Student Flex")

    def test_cannot_sign_up_to_archived_plan(self):
        res = self.signup(membershipPlan="Legacy Gold")
        self.assertEqual(res.status_code, 400)
        self.assertIn("membershipPlan", res.json()["error"])
        self.assertFalse(Member.objects.filter(username="lea").exists())

    def test_cannot_sign_up_to_unknown_plan(self):
        res = self.signup(membershipPlan="Platinum")
        self.assertEqual(res.status_code, 400)
        self.assertIn("membershipPlan", res.json()["error"])

    def test_branch_is_required(self):
        res = self.signup(branch="")
        self.assertEqual(res.status_code, 400)
        self.assertIn("branch", res.json()["error"])

    def test_walk_in_registration_uses_the_same_plan_rules(self):
        role = Role.objects.create(name="Receptionist", permissions=["manage_members"])
        account = StaffAccount(
            full_name="Desk", email="desk@gym.com", username="desk",
            job_title=StaffAccount.JobTitle.RECEPTIONIST, role=role,
        )
        account.set_password(PASSWORD)
        account.save()
        staff_login(self.client, "desk", PASSWORD)

        walk_in = {
            "name": "Sami", "email": "sami@example.com", "phone": "71000000", "branch": "Jnah",
            "paymentMethod": "Cash", "paymentDuration": "1 Month",
            **SIGNED_WAIVER, "signatureName": "Sami",
        }
        ok = self.client.post("/api/members", {**walk_in, "membershipPlan": "Basic"}, content_type="application/json")
        self.assertEqual(ok.status_code, 201, ok.content)

        archived = self.client.post(
            "/api/members", {**walk_in, "membershipPlan": "Legacy Gold"}, content_type="application/json"
        )
        self.assertEqual(archived.status_code, 400)


# User story (SCRUM-83): "As a member, I want to sign a digital waiver and
# health disclaimer during signup, so that the gym has liability
# protection on file before I start training."
class WaiverTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MembershipPlan.objects.create(name="Basic", price="35.00")
        role = Role.objects.create(name="Receptionist", permissions=["manage_members"])
        cls.desk = StaffAccount(
            full_name="Dana Desk", email="desk@gym.com", username="desk",
            job_title=StaffAccount.JobTitle.RECEPTIONIST, role=role,
        )
        cls.desk.set_password(PASSWORD)
        cls.desk.save()

    def signup(self, **overrides):
        payload = {
            "name": "Lea Haddad", "email": "lea@example.com", "phone": "70123456",
            "branch": "Hamra", "membershipPlan": "Basic", "username": "lea", "password": "Password123!",
            "paymentMethod": "Card", "paymentDuration": "1 Month",
            **SIGNED_WAIVER, "signatureName": "Lea Haddad",
        }
        payload.update(overrides)
        return self.client.post("/api/members/signup", payload, content_type="application/json")

    def walk_in(self, **overrides):
        staff_login(self.client, "desk", PASSWORD)
        payload = {
            "name": "Sami Khoury", "email": "sami@example.com", "phone": "71000000", "branch": "Jnah",
            "membershipPlan": "Basic", "paymentMethod": "Cash", "paymentDuration": "1 Month",
            **SIGNED_WAIVER, "signatureName": "Sami Khoury",
        }
        payload.update(overrides)
        return self.client.post("/api/members", payload, content_type="application/json")

    def test_waiver_text_is_public_and_versioned(self):
        res = self.client.get("/api/members/waiver")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["version"], WAIVER_VERSION)
        self.assertIn("assume all such risks", res.json()["liabilityWaiver"])
        self.assertIn("physician", res.json()["healthDisclaimer"])

    # --- online signup ---
    def test_online_signup_records_the_signed_waiver(self):
        res = self.signup(signatureName="  lea   haddad ")
        self.assertEqual(res.status_code, 201, res.content)
        waiver = res.json()["waiver"]
        self.assertEqual(waiver["signedVia"], "Online signup")
        self.assertEqual(waiver["waiverVersion"], WAIVER_VERSION)
        self.assertEqual(waiver["signatureName"], "lea haddad")
        self.assertIsNone(waiver["witnessedBy"])

        stored = Waiver.objects.get(member__username="lea")
        self.assertTrue(stored.liability_waiver_accepted and stored.health_disclaimer_accepted)
        # The member sees it on their own account too.
        self.assertEqual(self.client.get("/api/members/me").json()["waiver"]["signedVia"], "Online signup")

    def test_online_signup_needs_both_boxes(self):
        for field in ("liabilityWaiverAccepted", "healthDisclaimerAccepted"):
            res = self.signup(**{field: False})
            self.assertEqual(res.status_code, 400, field)
            self.assertIn(field, res.json()["error"])
        res = self.signup(liabilityWaiverAccepted=None, healthDisclaimerAccepted=None)
        self.assertEqual(res.status_code, 400)
        self.assertFalse(Member.objects.exists())

    def test_online_signup_needs_a_matching_signature(self):
        for signature in ("", "Someone Else"):
            res = self.signup(signatureName=signature)
            self.assertEqual(res.status_code, 400, signature)
            self.assertIn("signatureName", res.json()["error"])
        self.assertFalse(Member.objects.exists())
        # No payment is taken for a refused signup either.
        self.assertEqual(Payment.objects.count(), 0)

    # --- walk-in registration ---
    def test_walk_in_records_waiver_witnessed_by_the_receptionist(self):
        res = self.walk_in()
        self.assertEqual(res.status_code, 201, res.content)
        waiver = res.json()["waiver"]
        self.assertEqual(waiver["signedVia"], "Front desk")
        self.assertEqual(waiver["witnessedBy"], "Dana Desk")

        member_id = res.json()["id"]
        detail = self.client.get(f"/api/members/{member_id}").json()
        self.assertEqual(detail["waiver"]["signatureName"], "Sami Khoury")
        listed = self.client.get("/api/members?q=Sami").json()["results"][0]
        self.assertEqual(listed["waiver"]["signedVia"], "Front desk")

    def test_walk_in_without_waiver_is_refused(self):
        res = self.walk_in(liabilityWaiverAccepted=False, signatureName="")
        self.assertEqual(res.status_code, 400)
        self.assertIn("liabilityWaiverAccepted", res.json()["error"])
        self.assertFalse(Member.objects.filter(email="sami@example.com").exists())

    def test_member_without_waiver_shows_none(self):
        member = Member.objects.create(name="Old Record", email="old@example.com", phone="1", branch="Hamra",
                                       join_date="2024-01-01")
        staff_login(self.client, "desk", PASSWORD)
        self.assertIsNone(self.client.get(f"/api/members/{member.id}").json()["waiver"])


# Every customer without a valid subscription - expired, or never paid for
# one - is Frozen until they pay; Cancelled members are left as they are.
class SubscriptionStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MembershipPlan.objects.create(name="Basic", price="25.00")
        role = Role.objects.create(name="Receptionist", permissions=["manage_members"])
        desk = StaffAccount(
            full_name="Desk", email="desk@gym.com", username="desk",
            job_title=StaffAccount.JobTitle.RECEPTIONIST, role=role,
        )
        desk.set_password(PASSWORD)
        desk.save()

        today = timezone.localdate()

        def member(name, status="Active", expires=None):
            return Member.objects.create(
                name=name, email=f"{name.lower()}@example.com", phone="1", branch="Hamra",
                join_date=today, status=status, subscription_expires_at=expires,
            )

        cls.never_paid = member("Never")
        cls.lapsed = member("Lapsed", expires=today - timedelta(days=1))
        cls.last_day = member("Lastday", expires=today)
        cls.paid = member("Paid", expires=today + timedelta(days=30))
        cls.cancelled = member("Cancelled", status="Cancelled")

    def setUp(self):
        staff_login(self.client, "desk", PASSWORD)

    def test_directory_freezes_members_without_a_valid_subscription(self):
        results = self.client.get("/api/members").json()["results"]
        self.assertEqual({m["name"]: m["status"] for m in results}, {
            "Never": "Frozen", "Lapsed": "Frozen", "Lastday": "Active", "Paid": "Active", "Cancelled": "Cancelled",
        })

    def test_member_detail_freezes_a_member_who_never_paid(self):
        res = self.client.get(f"/api/members/{self.never_paid.id}")
        self.assertEqual(res.json()["status"], "Frozen")
        self.assertIsNone(res.json()["subscriptionExpiresAt"])

    def test_check_in_is_refused_without_a_valid_subscription(self):
        res = self.client.post("/api/checkins", {"membershipId": self.never_paid.id}, content_type="application/json")
        self.assertEqual(res.json()["checkIn"]["result"], "Denied")
        self.assertEqual(res.json()["checkIn"]["reason"], "Frozen")

    def test_member_sees_frozen_on_their_own_account(self):
        self.client.post("/api/auth/logout")
        self.never_paid.username = "never"
        self.never_paid.set_password(PASSWORD)
        self.never_paid.save()
        res = self.client.post("/api/members/login", {"username": "never", "password": PASSWORD},
                               content_type="application/json")
        self.assertEqual(res.json()["status"], "Frozen")
        self.assertEqual(self.client.get("/api/members/me").json()["status"], "Frozen")

    def test_paying_makes_them_active_again(self):
        res = self.client.post(f"/api/members/{self.never_paid.id}/payments",
                               {"membershipPlan": "Basic", "method": "Cash", "duration": "1 Month"},
                               content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["status"], "Active")
        self.assertIsNotNone(res.json()["subscriptionExpiresAt"])

