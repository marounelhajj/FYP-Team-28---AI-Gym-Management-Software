from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from administration.models import Role, StaffAccount

from .models import BranchPromotion, MembershipPlan


class PlansTestBase(APITestCase):
    def setUp(self):
        gm_role = Role.objects.create(name="General Manager", permissions=["manage_membership_plans"])
        bm_role = Role.objects.create(name="Branch Manager", permissions=["manage_members", "manage_branch_promotions"])
        receptionist_role = Role.objects.create(name="Receptionist", permissions=["manage_members"])
        self.gm = self._make_account("gm", gm_role)
        self.branch_manager = self._make_account("bm", bm_role)
        self.receptionist = self._make_account("desk", receptionist_role)
        self.basic = MembershipPlan.objects.create(name="Basic", price="35.00", features=["Gym floor"])

    def _make_account(self, username, role):
        account = StaffAccount(
            full_name=username.title(), email=f"{username}@gym.com", username=username,
            job_title="General Manager", role=role,
        )
        account.set_password("Password123!")
        account.save()
        return account

    def _login(self, account):
        res = self.client.post("/api/auth/login", {"username": account.username, "password": "Password123!"}, format="json")
        self.assertEqual(res.status_code, 200)


class MembershipPlanApiTests(PlansTestBase):
    def test_anyone_can_list_plans(self):
        res = self.client.get("/api/plans")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["total"], 1)
        self.assertEqual(res.data["results"][0]["name"], "Basic")

    def test_general_manager_can_create_plan(self):
        self._login(self.gm)
        res = self.client.post("/api/plans", {
            "name": "Premium Annual", "price": "900.00", "billingCycle": "Annual",
            "features": ["All branches", "  "],
        }, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["monthlyEquivalent"], "75.00")
        self.assertEqual(res.data["features"], ["All branches"])  # blank entries dropped
        self.assertTrue(res.data["isActive"])

    def test_create_requires_login(self):
        res = self.client.post("/api/plans", {"name": "X", "price": "10"}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_create_requires_manage_plans_permission(self):
        self._login(self.receptionist)
        res = self.client.post("/api/plans", {"name": "X", "price": "10"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertFalse(MembershipPlan.objects.filter(name="X").exists())

    def test_rejects_duplicate_name_case_insensitively(self):
        self._login(self.gm)
        res = self.client.post("/api/plans", {"name": "basic", "price": "10"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("name", res.data["error"])

    def test_rejects_negative_price(self):
        self._login(self.gm)
        res = self.client.post("/api/plans", {"name": "Cheap", "price": "-5"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("price", res.data["error"])

    def test_general_manager_can_change_price_and_archive(self):
        self._login(self.gm)
        res = self.client.patch(f"/api/plans/{self.basic.id}", {"price": "40.00"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["price"], "40.00")

        res = self.client.patch(f"/api/plans/{self.basic.id}", {"isActive": False}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["isActive"])

        active = self.client.get("/api/plans?isActive=true")
        self.assertEqual(active.data["total"], 0)

    def test_receptionist_cannot_edit_plan(self):
        self._login(self.receptionist)
        res = self.client.patch(f"/api/plans/{self.basic.id}", {"price": "1.00"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.basic.refresh_from_db()
        self.assertEqual(str(self.basic.price), "35.00")

    def test_unknown_plan_returns_404(self):
        res = self.client.get("/api/plans/999")
        self.assertEqual(res.status_code, 404)

    def test_meta_lists_billing_cycles(self):
        res = self.client.get("/api/plans/meta")
        self.assertEqual(res.data["billingCycles"], ["Monthly", "Quarterly", "Semi-Annual", "Annual"])


class BranchPromotionApiTests(PlansTestBase):
    def setUp(self):
        super().setUp()
        self.premium = MembershipPlan.objects.create(
            name="Premium", price="100.00", max_promo_discount_percent="20.00"
        )
        self.today = timezone.localdate()

    def _promo_payload(self, **overrides):
        payload = {
            "planId": self.premium.id, "branch": "Hamra", "name": "Summer deal",
            "discountType": "Percent", "discountValue": "15",
            "startDate": str(self.today), "endDate": str(self.today + timedelta(days=10)),
        }
        payload.update(overrides)
        return payload

    def test_branch_manager_can_create_promotion_within_cap(self):
        self._login(self.branch_manager)
        res = self.client.post("/api/plans/promotions", self._promo_payload(), format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["effectivePrice"], "85.00")
        self.assertEqual(res.data["status"], "Running")
        self.assertEqual(res.data["createdBy"], "Bm")

    def test_rejects_percent_discount_over_plan_cap(self):
        self._login(self.branch_manager)
        res = self.client.post("/api/plans/promotions", self._promo_payload(discountValue="25"), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("discountValue", res.data["error"])

    def test_rejects_fixed_discount_over_plan_cap(self):
        self._login(self.branch_manager)
        res = self.client.post(
            "/api/plans/promotions", self._promo_payload(discountType="Fixed", discountValue="21"), format="json"
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("discountValue", res.data["error"])

    def test_rejects_end_date_before_start(self):
        self._login(self.branch_manager)
        res = self.client.post(
            "/api/plans/promotions",
            self._promo_payload(endDate=str(self.today - timedelta(days=1))),
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("endDate", res.data["error"])

    def test_rejects_promotion_on_archived_plan(self):
        self.premium.is_active = False
        self.premium.save()
        self._login(self.branch_manager)
        res = self.client.post("/api/plans/promotions", self._promo_payload(), format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("planId", res.data["error"])

    def test_receptionist_cannot_create_promotion(self):
        self._login(self.receptionist)
        res = self.client.post("/api/plans/promotions", self._promo_payload(), format="json")
        self.assertEqual(res.status_code, 403)

    def test_branch_manager_cannot_change_org_wide_price(self):
        self._login(self.branch_manager)
        res = self.client.patch(f"/api/plans/{self.premium.id}", {"price": "50.00"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_pricing_applies_best_running_promotion_for_that_branch_only(self):
        BranchPromotion.objects.create(
            plan=self.premium, branch="Hamra", name="Small", discount_type="Percent", discount_value="5",
            start_date=self.today, end_date=self.today,
        )
        BranchPromotion.objects.create(
            plan=self.premium, branch="Hamra", name="Big", discount_type="Fixed", discount_value="12",
            start_date=self.today, end_date=self.today,
        )
        BranchPromotion.objects.create(  # expired - must be ignored
            plan=self.premium, branch="Hamra", name="Old", discount_type="Percent", discount_value="20",
            start_date=self.today - timedelta(days=10), end_date=self.today - timedelta(days=1),
        )

        hamra = {p["name"]: p for p in self.client.get("/api/plans/pricing?branch=Hamra").data["results"]}
        self.assertEqual(hamra["Premium"]["effectivePrice"], "88.00")
        self.assertEqual(hamra["Premium"]["promotion"]["name"], "Big")
        self.assertEqual(hamra["Basic"]["effectivePrice"], "35.00")

        jnah = {p["name"]: p for p in self.client.get("/api/plans/pricing?branch=Jnah").data["results"]}
        self.assertEqual(jnah["Premium"]["effectivePrice"], "100.00")
        self.assertIsNone(jnah["Premium"]["promotion"])

    def test_lowering_cap_shrinks_existing_promotions(self):
        BranchPromotion.objects.create(
            plan=self.premium, branch="Hamra", name="Deal", discount_type="Percent", discount_value="20",
            start_date=self.today, end_date=self.today,
        )
        self._login(self.gm)
        self.client.patch(f"/api/plans/{self.premium.id}", {"maxPromoDiscountPercent": "10"}, format="json")

        hamra = {p["name"]: p for p in self.client.get("/api/plans/pricing?branch=Hamra").data["results"]}
        self.assertEqual(hamra["Premium"]["effectivePrice"], "90.00")

    def test_pricing_requires_valid_branch(self):
        self.assertEqual(self.client.get("/api/plans/pricing").status_code, 400)
        self.assertEqual(self.client.get("/api/plans/pricing?branch=Mars").status_code, 400)

    def test_cancel_promotion(self):
        promo = BranchPromotion.objects.create(
            plan=self.premium, branch="Hamra", name="Deal", discount_type="Percent", discount_value="10",
            start_date=self.today, end_date=self.today,
        )
        self._login(self.branch_manager)
        res = self.client.patch(f"/api/plans/promotions/{promo.id}", {"isActive": False}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "Cancelled")
