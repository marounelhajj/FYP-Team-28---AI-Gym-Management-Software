from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from administration.models import Role, StaffAccount
from administration.testing import staff_login

from .models import MarketingCampaign


class MarketingTestBase(APITestCase):
    def setUp(self):
        gm_role = Role.objects.create(name="General Manager", permissions=["view_marketing_campaigns"])
        mkt_role = Role.objects.create(name="Marketing Staff", permissions=["manage_marketing_campaigns"])
        desk_role = Role.objects.create(name="Receptionist", permissions=["manage_members"])
        self.gm = self._make_account("gm", gm_role)
        self.marketer = self._make_account("mkt", mkt_role)
        self.desk = self._make_account("desk", desk_role)

    def _make_account(self, username, role):
        account = StaffAccount(
            full_name=username.title(), email=f"{username}@gym.com", username=username,
            job_title="General Manager", role=role,
        )
        account.set_password("Password123!")
        account.save()
        return account

    def _login(self, account):
        res = staff_login(self.client, account.username, "Password123!")
        self.assertEqual(res.status_code, 200)

    def _campaign(self, branch="Hamra", name="Summer Push", budget="1000.00", spent="0.00", days_from_now=0, length=10):
        start = timezone.localdate() + timedelta(days=days_from_now)
        return MarketingCampaign.objects.create(
            branch=branch, name=name, strategy="Social ads + in-branch flyers.",
            budget=budget, amount_spent=spent, start_date=start, end_date=start + timedelta(days=length),
        )


class CampaignManagementTests(MarketingTestBase):
    def test_marketing_staff_can_create_a_campaign(self):
        self._login(self.marketer)
        res = self.client.post("/api/marketing/campaigns", {
            "branch": "Jnah", "name": "Ramadan Promo", "strategy": "Discounted PT bundles.",
            "budget": "500.00", "startDate": "2026-01-01", "endDate": "2026-01-31",
        }, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["branch"], "Jnah")
        self.assertEqual(res.data["amountSpent"], "0.00")
        self.assertEqual(res.data["status"], "Expired")  # dates are in the past relative to "today" in tests
        self.assertEqual(res.data["createdBy"], "Mkt")

    def test_creating_a_campaign_requires_the_permission(self):
        self._login(self.desk)
        res = self.client.post("/api/marketing/campaigns", {
            "branch": "Jnah", "name": "Ramadan Promo", "budget": "500.00",
            "startDate": "2026-01-01", "endDate": "2026-01-31",
        }, format="json")
        self.assertEqual(res.status_code, 403)

    def test_a_general_manager_cannot_create_a_campaign(self):
        # Reading the cross-branch report and running a campaign are
        # different privileges - view_marketing_campaigns alone isn't enough.
        self._login(self.gm)
        res = self.client.post("/api/marketing/campaigns", {
            "branch": "Jnah", "name": "Ramadan Promo", "budget": "500.00",
            "startDate": "2026-01-01", "endDate": "2026-01-31",
        }, format="json")
        self.assertEqual(res.status_code, 403)

    def test_end_date_before_start_date_is_rejected(self):
        self._login(self.marketer)
        res = self.client.post("/api/marketing/campaigns", {
            "branch": "Jnah", "name": "Bad Dates", "budget": "500.00",
            "startDate": "2026-02-10", "endDate": "2026-02-01",
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("endDate", res.data["error"])

    def test_budget_must_be_positive(self):
        self._login(self.marketer)
        res = self.client.post("/api/marketing/campaigns", {
            "branch": "Jnah", "name": "Free Campaign", "budget": "0.00",
            "startDate": "2026-02-01", "endDate": "2026-02-10",
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("budget", res.data["error"])

    def test_marketing_staff_can_list_and_filter_by_branch(self):
        self._campaign(branch="Hamra")
        self._campaign(branch="Jnah", name="Jnah Launch")
        self._login(self.marketer)
        res = self.client.get("/api/marketing/campaigns?branch=Jnah")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["total"], 1)
        self.assertEqual(res.data["results"][0]["name"], "Jnah Launch")

    def test_general_manager_cannot_reach_the_management_list(self):
        self._login(self.gm)
        res = self.client.get("/api/marketing/campaigns")
        self.assertEqual(res.status_code, 403)

    def test_updating_spend_is_audit_logged(self):
        campaign = self._campaign(spent="100.00")
        self._login(self.marketer)
        res = self.client.patch(f"/api/marketing/campaigns/{campaign.id}", {"amountSpent": "250.00"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["amountSpent"], "250.00")

        from audit.models import AuditLog
        entry = AuditLog.objects.filter(action=AuditLog.Action.CAMPAIGN_UPDATED).first()
        self.assertIsNotNone(entry)
        self.assertIn("amountSpent", entry.details["changes"])

    def test_cancelling_a_campaign_sets_status(self):
        campaign = self._campaign()
        self._login(self.marketer)
        res = self.client.patch(f"/api/marketing/campaigns/{campaign.id}", {"isActive": False}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "Cancelled")

    def test_invalid_branch_is_rejected(self):
        self._login(self.marketer)
        res = self.client.get("/api/marketing/campaigns?branch=Nowhere")
        self.assertEqual(res.status_code, 400)


class CampaignReportTests(MarketingTestBase):
    def test_general_manager_sees_every_branch_even_with_no_campaigns(self):
        self._campaign(branch="Hamra", budget="1000.00", spent="400.00")
        self._login(self.gm)
        res = self.client.get("/api/marketing/report")
        self.assertEqual(res.status_code, 200)
        branches = {b["branch"]: b for b in res.data["branches"]}
        self.assertEqual(set(branches), {"Hamra", "Achrafieh", "Jnah", "Zalka"})
        self.assertEqual(branches["Hamra"]["campaignCount"], 1)
        self.assertEqual(branches["Hamra"]["budget"], "1000.00")
        self.assertEqual(branches["Hamra"]["spent"], "400.00")
        self.assertEqual(branches["Achrafieh"]["campaignCount"], 0)
        self.assertEqual(branches["Achrafieh"]["budget"], "0.00")

    def test_totals_sum_every_branch(self):
        self._campaign(branch="Hamra", budget="1000.00", spent="400.00")
        self._campaign(branch="Jnah", name="Jnah Push", budget="600.00", spent="600.00")
        self._login(self.gm)
        res = self.client.get("/api/marketing/report")
        self.assertEqual(res.data["totals"], {"budget": "1600.00", "spent": "1000.00"})

    def test_narrowing_to_one_branch(self):
        self._campaign(branch="Hamra", budget="1000.00", spent="400.00")
        self._campaign(branch="Jnah", name="Jnah Push", budget="600.00", spent="600.00")
        self._login(self.gm)
        res = self.client.get("/api/marketing/report?branch=Jnah")
        self.assertEqual(len(res.data["branches"]), 1)
        self.assertEqual(res.data["branches"][0]["branch"], "Jnah")
        self.assertEqual(res.data["totals"], {"budget": "600.00", "spent": "600.00"})

    def test_report_includes_strategy_text(self):
        self._campaign(branch="Hamra")
        self._login(self.gm)
        res = self.client.get("/api/marketing/report?branch=Hamra")
        self.assertEqual(res.data["branches"][0]["campaigns"][0]["strategy"], "Social ads + in-branch flyers.")

    def test_marketing_staff_cannot_reach_the_report(self):
        self._login(self.marketer)
        res = self.client.get("/api/marketing/report")
        self.assertEqual(res.status_code, 403)

    def test_report_requires_authentication(self):
        res = self.client.get("/api/marketing/report")
        self.assertEqual(res.status_code, 401)
