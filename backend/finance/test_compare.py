from datetime import date, datetime, time
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from billing.models import Payment
from members.models import Member
from retail.models import Sale

from .compare import resolve_period
from .models import Expense
from .tests import PASSWORD, _member, _staff
from administration.testing import staff_login

# SCRUM-105: comparing every branch's revenue in one view.

OCTOBER = "?period=custom&dateFrom=2026-10-01&dateTo=2026-10-31"


def _at(day):
    return timezone.make_aware(datetime.combine(day, time(12, 0)))


class CompareBranchesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _staff("gm", "Rami GM", ["view_financial_reports", "view_all_branches"])
        _staff("bm", "Karim BM", ["view_financial_reports"], branch="Hamra")
        members = {}
        for branch, count in [("Hamra", 4), ("Achrafieh", 2), ("Jnah", 4)]:
            members[branch] = [_member(f"{branch} {i}", branch, f"{branch.lower()}{i}") for i in range(count)]
        # Frozen members don't count towards revenue per member.
        Member.objects.filter(pk=_member("Frozen", "Jnah", "frozen").pk).update(status=Member.Status.FROZEN)

        def pay(branch, amount, day):
            p = Payment.objects.create(member=members[branch][0], amount=Decimal(amount), method="Cash",
                                       duration="1 Month", expires_at=day, note="Renewal")
            Payment.objects.filter(pk=p.pk).update(paid_at=_at(day))

        def sell(branch, total, day, voided=False):
            s = Sale.objects.create(branch=branch, payment_method="Cash", total=Decimal(total))
            Sale.objects.filter(pk=s.pk).update(sold_at=_at(day), voided_at=_at(day) if voided else None)

        def spend(branch, amount, day):
            Expense.objects.create(branch=branch, category=Expense.Category.RENT, amount=Decimal(amount), incurred_on=day)

        # October (the period) and September (the one before).
        pay("Hamra", "1000.00", date(2026, 10, 5))
        sell("Hamra", "100.00", date(2026, 10, 6))
        sell("Hamra", "999.00", date(2026, 10, 7), voided=True)
        pay("Hamra", "900.00", date(2026, 9, 5))
        spend("Hamra", "600.00", date(2026, 10, 1))

        pay("Achrafieh", "800.00", date(2026, 10, 5))
        pay("Achrafieh", "1000.00", date(2026, 9, 5))
        spend("Achrafieh", "300.00", date(2026, 10, 1))

        pay("Jnah", "300.00", date(2026, 10, 5))
        pay("Jnah", "300.00", date(2026, 9, 5))
        spend("Jnah", "500.00", date(2026, 10, 1))
        # Zalka: no members, no money.

    def setUp(self):
        staff_login(self.client, "gm", PASSWORD)

    def compare(self, query=OCTOBER):
        res = self.client.get(f"/api/finance/compare{query}")
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def rows(self, body=None):
        return {b["branch"]: b for b in (body or self.compare())["branches"]}

    def test_every_branch_ranked_by_revenue(self):
        body = self.compare()
        self.assertEqual([(b["rank"], b["branch"], b["revenue"]) for b in body["branches"]],
                         [(1, "Hamra", "1100.00"), (2, "Achrafieh", "800.00"), (3, "Jnah", "300.00"), (4, "Zalka", "0.00")])
        hamra = body["branches"][0]
        self.assertEqual(hamra["revenueBySource"], {"memberships": "1000.00", "retail": "100.00"})   # voided sale left out
        self.assertEqual((hamra["expenses"], hamra["net"], hamra["marginPercent"], hamra["sharePercent"]),
                         ("600.00", "500.00", 45.5, 50.0))

    def test_against_the_previous_period(self):
        body = self.compare()
        self.assertEqual(body["previous"], {"dateFrom": "2026-08-31", "dateTo": "2026-09-30"})
        rows = self.rows(body)
        self.assertEqual((rows["Hamra"]["previousRevenue"], rows["Hamra"]["growthPercent"]), ("900.00", 22.2))
        self.assertEqual(rows["Achrafieh"]["growthPercent"], -20.0)
        self.assertIsNone(rows["Zalka"]["growthPercent"])                      # nothing to compare with

    def test_revenue_per_active_member(self):
        body = self.compare()
        rows = self.rows(body)
        self.assertEqual((rows["Hamra"]["activeMembers"], rows["Hamra"]["revenuePerMember"]), (4, "275.00"))
        self.assertEqual((rows["Jnah"]["activeMembers"], rows["Jnah"]["revenuePerMember"]), (4, "75.00"))
        self.assertIsNone(rows["Zalka"]["revenuePerMember"])
        self.assertEqual((body["totals"]["activeMembers"], body["totals"]["revenuePerMember"]), (10, "220.00"))

    def test_underperforming_branches_and_why(self):
        body = self.compare()
        flags = {b["branch"]: [f["code"] for f in b["flags"]] for b in body["branches"]}
        self.assertEqual(flags, {
            "Hamra": [],
            "Achrafieh": ["declining"],                                 # -20% on September
            "Jnah": ["loss", "low_revenue", "low_per_member"],          # 300 vs 550 average; $75 vs $220 a member
            "Zalka": ["low_revenue"],
        })
        self.assertEqual(body["underperformingCount"], 3)
        jnah = self.rows(body)["Jnah"]
        self.assertTrue(jnah["underperforming"])
        self.assertEqual(jnah["flags"][0]["text"], "Running at a loss of $200.00")
        self.assertEqual(jnah["flags"][1]["text"], "Revenue 55% of the branch average")

    def test_company_totals(self):
        totals = self.compare()["totals"]
        self.assertEqual(totals, {
            "revenue": "2200.00", "expenses": "1400.00", "net": "800.00", "marginPercent": 36.4,
            "previousRevenue": "2200.00", "growthPercent": 0.0, "averageRevenue": "550.00",
            "activeMembers": 10, "revenuePerMember": "220.00",
        })

    def test_six_month_trend_per_branch(self):
        trend = self.compare()["trend"]
        self.assertEqual(trend["months"], ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"])
        hamra = next(s for s in trend["series"] if s["branch"] == "Hamra")
        self.assertEqual(hamra["revenue"][-2:], ["900.00", "1100.00"])

    def test_invalid_periods(self):
        for query in ["?period=decade", "?period=custom&dateFrom=2026-10-01",
                      "?period=custom&dateFrom=2026-10-31&dateTo=2026-10-01",
                      "?period=custom&dateFrom=2025-01-01&dateTo=2026-10-01"]:
            self.assertEqual(self.client.get(f"/api/finance/compare{query}").status_code, 400, query)

    def test_only_roles_that_see_every_branch(self):
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/finance/compare").status_code, 401)
        staff_login(self.client, "bm", PASSWORD)
        self.assertEqual(self.client.get("/api/finance/compare").status_code, 403)
        self.client.post("/api/auth/logout")
        _staff("desk", "Dana Desk", ["view_all_branches"], branch="Hamra")
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.client.get("/api/finance/compare").status_code, 403)


class PeriodTests(SimpleTestCase):
    TODAY = date(2026, 11, 18)

    def period(self, name, today=TODAY, **extra):
        result = resolve_period({"period": name, **extra}, today)
        self.assertIsNone(result[-1])
        return tuple(d.isoformat() for d in result[1:5])

    def test_a_running_period_is_compared_like_for_like(self):
        self.assertEqual(self.period("this_month"), ("2026-11-01", "2026-11-18", "2026-10-01", "2026-10-18"))
        self.assertEqual(self.period("this_quarter"), ("2026-10-01", "2026-11-18", "2026-07-01", "2026-08-18"))
        self.assertEqual(self.period("this_year"), ("2026-01-01", "2026-11-18", "2025-01-01", "2025-11-18"))
        # The 31st against a shorter month.
        self.assertEqual(self.period("this_month", today=date(2026, 3, 31)), ("2026-03-01", "2026-03-31", "2026-02-01", "2026-02-28"))

    def test_a_finished_period_is_compared_with_the_whole_one_before(self):
        self.assertEqual(self.period("last_month"), ("2026-10-01", "2026-10-31", "2026-09-01", "2026-09-30"))
        self.assertEqual(self.period("last_quarter"), ("2026-07-01", "2026-09-30", "2026-04-01", "2026-06-30"))
        self.assertEqual(self.period("last_month", today=date(2026, 1, 10)), ("2025-12-01", "2025-12-31", "2025-11-01", "2025-11-30"))

    def test_custom_is_compared_with_the_same_length_just_before(self):
        self.assertEqual(self.period("custom", dateFrom="2026-10-10", dateTo="2026-10-19"),
                         ("2026-10-10", "2026-10-19", "2026-09-30", "2026-10-09"))
