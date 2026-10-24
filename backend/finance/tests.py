from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from billing.models import Payment
from members.models import Member
from plans.models import MembershipPlan

from .models import Expense

PASSWORD = "ChangeMe123!"


def _staff(username, full_name, permissions, branch=None, role_name=None):
    role = Role.objects.create(name=role_name or f"{username} role", permissions=permissions)
    account = StaffAccount(
        full_name=full_name, email=f"{username}@gym.com", username=username,
        job_title=StaffAccount.JobTitle.RECEPTIONIST, role=role, branch=branch,
    )
    account.set_password(PASSWORD)
    account.save()
    return account


def _member(name, branch, username):
    today = timezone.localdate()
    member = Member(
        name=name, email=f"{username}@example.com", phone="70000000", branch=branch,
        join_date=today, membership_plan="Basic", username=username,
    )
    member.set_password(PASSWORD)
    member.save()
    return member


# User story: "As a general manager, I want to view expense and revenue
# data for each branch, so that I can monitor financial performance and
# compare branches."
class FinancialReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MembershipPlan.objects.create(name="Basic", price="25.00")
        cls.gm = _staff("gm", "Rami GM", ["view_financial_reports", "view_all_branches"], role_name="General Manager")
        cls.bm = _staff(
            "bm", "Karim BM", ["view_financial_reports"], branch="Hamra", role_name="Branch Manager",
        )
        _staff("desk", "Dana Desk", ["manage_members"], branch="Hamra", role_name="Receptionist")

        cls.hamra_member = _member("Lea Haddad", "Hamra", "lea")
        cls.jnah_member = _member("Sami Khoury", "Jnah", "sami")

        now = timezone.now()

        def payment(member, amount, days_ago):
            p = Payment.objects.create(
                member=member, amount=amount, method="Cash", duration="1 Month",
                expires_at=timezone.localdate(), note="Renewal",
            )
            Payment.objects.filter(id=p.id).update(paid_at=now - timedelta(days=days_ago))
            return p

        cls.hamra_payment_recent = payment(cls.hamra_member, Decimal("25.00"), 1)
        cls.hamra_payment_old = payment(cls.hamra_member, Decimal("300.00"), 20)
        cls.jnah_payment = payment(cls.jnah_member, Decimal("50.00"), 2)

        def expense(branch, category, amount, days_ago):
            return Expense.objects.create(
                branch=branch, category=category, amount=amount,
                incurred_on=timezone.localdate() - timedelta(days=days_ago),
            )

        cls.hamra_rent = expense("Hamra", Expense.Category.RENT, Decimal("100.00"), 1)
        cls.hamra_payroll = expense("Hamra", Expense.Category.PAYROLL, Decimal("50.00"), 20)
        cls.jnah_rent = expense("Jnah", Expense.Category.RENT, Decimal("40.00"), 2)

    def setUp(self):
        staff_login(self.client, "gm", PASSWORD)

    def report(self, query=""):
        res = self.client.get(f"/api/finance/report{query}")
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def by_branch(self, body):
        return {b["branch"]: b for b in body["branches"]}

    def test_every_branch_the_caller_can_see_is_listed_even_at_zero(self):
        body = self.report()
        by_branch = self.by_branch(body)
        self.assertEqual(set(by_branch), {"Hamra", "Achrafieh", "Jnah", "Zalka"})
        self.assertEqual(by_branch["Achrafieh"], {
            "branch": "Achrafieh", "revenue": "0.00", "revenueBySource": {"memberships": "0.00", "retail": "0.00"},
            "expenses": "0.00", "net": "0.00", "expensesByCategory": {},
        })

    def test_revenue_is_summed_from_payments_by_the_members_branch(self):
        by_branch = self.by_branch(self.report())
        self.assertEqual(by_branch["Hamra"]["revenue"], "325.00")
        self.assertEqual(by_branch["Jnah"]["revenue"], "50.00")

    def test_expenses_are_summed_and_broken_down_by_category(self):
        by_branch = self.by_branch(self.report())
        self.assertEqual(by_branch["Hamra"]["expenses"], "150.00")
        self.assertEqual(by_branch["Hamra"]["expensesByCategory"], {"Rent": "100.00", "Payroll": "50.00"})
        self.assertEqual(by_branch["Jnah"]["expensesByCategory"], {"Rent": "40.00"})

    def test_net_is_revenue_minus_expenses(self):
        by_branch = self.by_branch(self.report())
        self.assertEqual(by_branch["Hamra"]["net"], "175.00")  # 325.00 - 150.00
        self.assertEqual(by_branch["Jnah"]["net"], "10.00")  # 50.00 - 40.00

    def test_totals_sum_every_listed_branch(self):
        body = self.report()
        self.assertEqual(body["totals"], {"revenue": "375.00", "expenses": "190.00", "net": "185.00"})

    def test_branch_filter_narrows_to_one_branch(self):
        body = self.report("?branch=Hamra")
        self.assertEqual([b["branch"] for b in body["branches"]], ["Hamra"])
        self.assertEqual(body["totals"]["revenue"], "325.00")

    def test_date_range_filter(self):
        today = timezone.localdate()
        since = today - timedelta(days=5)
        body = self.report(f"?dateFrom={since}")
        by_branch = self.by_branch(body)
        # The 20-days-ago payment/payroll are excluded, the recent ones aren't.
        self.assertEqual(by_branch["Hamra"]["revenue"], "25.00")
        self.assertEqual(by_branch["Hamra"]["expenses"], "100.00")

    def test_invalid_branch_or_dates_are_rejected(self):
        for query in ("?branch=Paris", "?dateFrom=yesterday", "?dateFrom=2026-10-10&dateTo=2026-10-01"):
            self.assertEqual(self.client.get(f"/api/finance/report{query}").status_code, 400, query)

    def test_branch_manager_only_ever_sees_their_own_branch(self):
        self.client.post("/api/auth/logout")
        staff_login(self.client, "bm", PASSWORD)
        body = self.report()
        self.assertEqual([b["branch"] for b in body["branches"]], ["Hamra"])

    def test_branch_manager_cannot_ask_for_another_branch(self):
        self.client.post("/api/auth/logout")
        staff_login(self.client, "bm", PASSWORD)
        self.assertEqual(self.client.get("/api/finance/report?branch=Jnah").status_code, 403)

    def test_requires_view_financial_reports(self):
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/finance/report").status_code, 401)
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.client.get("/api/finance/report").status_code, 403)


# User story: the write side of the same feature - revenue already came
# from billing.Payment, but expenses had to be entered by someone first.
class ExpenseRecordingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = _staff(
            "admin", "Maya Admin", ["manage_billing", "view_all_branches"], role_name="System Administrator",
        )
        cls.bm = _staff("bm", "Karim BM", ["manage_billing"], branch="Hamra", role_name="Branch Manager")
        _staff("gm", "Rami GM", ["view_financial_reports"], role_name="General Manager")

    def setUp(self):
        staff_login(self.client, "admin", PASSWORD)

    def record(self, **body):
        return self.client.post("/api/finance/expenses", body, content_type="application/json")

    def test_records_an_expense(self):
        res = self.record(branch="Hamra", category="Rent", amount="1200.00", note="October rent")
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertEqual(body["branch"], "Hamra")
        self.assertEqual(body["amount"], "1200.00")
        self.assertEqual(body["recordedBy"], "Maya Admin")

        expense = Expense.objects.get()
        self.assertEqual(expense.recorded_by.username, "admin")

    def test_incurred_on_defaults_to_today(self):
        res = self.record(branch="Hamra", category="Utilities", amount="80.00")
        self.assertEqual(res.json()["incurredOn"], str(timezone.localdate()))

    def test_amount_must_be_positive(self):
        res = self.record(branch="Hamra", category="Rent", amount="0")
        self.assertEqual(res.status_code, 400)
        self.assertIn("amount", res.json()["error"])

    def test_invalid_branch_or_category_rejected(self):
        self.assertEqual(self.record(branch="Paris", category="Rent", amount="1").status_code, 400)
        self.assertEqual(self.record(branch="Hamra", category="Snacks", amount="1").status_code, 400)

    def test_branch_manager_can_only_record_for_their_own_branch(self):
        self.client.post("/api/auth/logout")
        staff_login(self.client, "bm", PASSWORD)
        res = self.record(branch="Hamra", category="Rent", amount="500.00")
        self.assertEqual(res.status_code, 201, res.content)
        res = self.record(branch="Jnah", category="Rent", amount="500.00")
        self.assertEqual(res.status_code, 403)

    def test_list_is_newest_incurred_first_and_filters_by_branch(self):
        self.record(branch="Hamra", category="Rent", amount="100.00")
        self.record(branch="Jnah", category="Rent", amount="50.00")
        res = self.client.get("/api/finance/expenses?branch=Hamra")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["results"][0]["branch"], "Hamra")

    def test_requires_manage_billing(self):
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/finance/expenses").status_code, 401)
        self.assertEqual(self.record(branch="Hamra", category="Rent", amount="1").status_code, 401)
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual(self.client.get("/api/finance/expenses").status_code, 403)
        self.assertEqual(self.record(branch="Hamra", category="Rent", amount="1").status_code, 403)


# The System Administrator role isn't tied to a branch but can open both
# finance screens, so it must see every branch rather than be refused.
class SystemAdministratorFinanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from administration.management.commands.seed_staff import ROLES

        permissions = next(r["permissions"] for r in ROLES if r["name"] == "System Administrator")
        _staff("admin", "Maya Admin", permissions, role_name="System Administrator")

    def test_report_and_expenses_load_for_a_branchless_administrator(self):
        staff_login(self.client, "admin", PASSWORD)
        self.assertEqual(self.client.get("/api/finance/report").status_code, 200)
        self.assertEqual(self.client.get("/api/finance/expenses").status_code, 200)
