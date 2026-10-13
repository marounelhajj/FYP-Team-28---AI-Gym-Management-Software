from django.test import TestCase

from administration.models import Role, StaffAccount
from plans.models import MembershipPlan

from .models import Member

PASSWORD = "ChangeMe123!"


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
        self.client.post("/api/auth/login", {"username": "desk", "password": PASSWORD}, content_type="application/json")

        walk_in = {"name": "Sami", "email": "sami@example.com", "phone": "71000000", "branch": "Jnah"}
        ok = self.client.post("/api/members", {**walk_in, "membershipPlan": "Basic"}, content_type="application/json")
        self.assertEqual(ok.status_code, 201, ok.content)

        archived = self.client.post(
            "/api/members", {**walk_in, "membershipPlan": "Legacy Gold"}, content_type="application/json"
        )
        self.assertEqual(archived.status_code, 400)
