from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog

from . import config
from .accuracy import branch_accuracy
from .features import week_start
from .models import BranchCallSettings, ChurnRun, ChurnScore, RetentionCall
from .scoring import refresh_branch
from .testing import PASSWORD, cancel, member, regular, staff

MANAGER = ["view_at_risk_members", "manage_at_risk_list", "log_retention_calls"]
DESK = ["view_at_risk_members", "log_retention_calls"]


def ranked_branch(count=8):
    """Members whose risk falls with i: member 0 is the most at risk."""
    out = []
    for i in range(count):
        m = member(f"Member{i} Hamra", expires_in=60)
        regular(m, per_week=3, recent_per_week=min(3, i // 2))
        out.append(m)
    return out


# User story (SCRUM-120): "As a branch manager, I want to cap the at-risk list
# to the number of calls my staff can make per week, so that the list stays
# actionable."
class CapacityTests(TestCase):
    def setUp(self):
        self.bm = staff("hamrabm", MANAGER, branch="Hamra")
        staff("desk", DESK, branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        staff("gm", [*MANAGER, "view_all_branches"], job_title=StaffAccount.JobTitle.GENERAL_MANAGER)
        self.members = ranked_branch()
        staff_login(self.client, "hamrabm", PASSWORD)

    def put(self, weekly, branch=""):
        return self.client.put("/api/churn/capacity", {"branch": branch, "weeklyCapacity": weekly},
                               content_type="application/json")

    def body(self):
        return self.client.get("/api/churn/at-risk").json()

    def test_default_capacity_is_20(self):
        body = self.body()
        self.assertEqual(body["capacity"]["weekly"], config.DEFAULT_CALL_CAPACITY)
        self.assertEqual(len(body["members"]), 8)
        self.assertEqual(body["belowCap"], [])

    # AC: weekly call capacity is configurable per branch.
    def test_branch_manager_sets_their_branchs_capacity(self):
        res = self.put(3)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(BranchCallSettings.objects.get(branch="Hamra").weekly_capacity, 3)
        self.assertEqual(res.json()["capacity"]["weekly"], 3)
        self.assertFalse(BranchCallSettings.objects.filter(branch="Jnah").exists())
        # Next week's list starts with the branch's capacity too.
        next_monday = week_start(timezone.localdate()) + timedelta(days=7)
        with mock.patch("django.utils.timezone.localdate", return_value=next_monday):
            self.assertEqual(refresh_branch("Hamra").call_capacity, 3)
        entry = AuditLog.objects.get(action=AuditLog.Action.CALL_CAPACITY_UPDATED)
        self.assertEqual(entry.details["changes"]["weeklyCapacity"], [20, 3])
        self.assertEqual(entry.branch, "Hamra")

    def test_capacity_permissions_and_validation(self):
        self.assertEqual(self.put(5, "Jnah").status_code, 403)
        for bad in [0, -1, "five", config.MAX_CALL_CAPACITY + 1, None]:
            self.assertEqual(self.put(bad).status_code, 400, bad)
        self.client.logout()
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.put(5).status_code, 403)
        self.assertFalse(self.body()["capacity"]["canEdit"])
        self.client.logout()
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual(self.put(7, "Jnah").status_code, 200)
        self.assertEqual(BranchCallSettings.objects.get(branch="Jnah").weekly_capacity, 7)

    # AC: the list is trimmed to that capacity; the rest stay visible below the cap.
    def test_list_is_trimmed_to_capacity(self):
        body = self.put(3).json()
        self.assertEqual([m["rank"] for m in body["members"]], [1, 2, 3])
        self.assertEqual([m["rank"] for m in body["belowCap"]], [4, 5, 6, 7, 8])
        self.assertEqual(body["members"][0]["memberId"], self.members[0].pk)

    def test_contacted_members_drop_off_and_no_answer_stays(self):
        body = self.put(3).json()
        first, second = body["members"][0]["memberId"], body["members"][1]["memberId"]
        self.client.post("/api/churn/calls", {"memberId": first, "outcome": "saved"}, content_type="application/json")
        self.client.post("/api/churn/calls", {"memberId": second, "outcome": "no_answer"}, content_type="application/json")
        body = self.body()
        # Calls made count against the week's capacity: ranks 2 and 3 are left.
        self.assertEqual([m["rank"] for m in body["members"]], [2, 3])
        self.assertEqual([m["memberId"] for m in body["contacted"]], [first])
        self.assertEqual(body["accuracy"]["thisWeek"]["contacted"], 1)
        self.assertEqual(body["accuracy"]["thisWeek"]["toCall"], 2)
        self.assertEqual(body["accuracy"]["thisWeek"]["noAnswer"], 1)
        self.assertEqual(body["accuracy"]["thisWeek"]["saved"], 1)

    def test_raising_the_capacity_mid_week_brings_more_members_in(self):
        self.put(3)
        body = self.put(5).json()
        self.assertEqual([m["rank"] for m in body["members"]], [1, 2, 3, 4, 5])
        self.assertEqual(ChurnRun.objects.get(branch="Hamra").call_capacity, 5)


# AC: accuracy is tracked against completed calls.
class AccuracyTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.m = [member(f"M{i} Test") for i in range(7)]
        m = self.m

        def week(days_ago, ranked, capacity=2):
            as_of = today - timedelta(days=days_ago)
            run = ChurnRun.objects.create(branch="Hamra", week_start=week_start(as_of), as_of=as_of, method="rules",
                                          trigger="scheduled", call_capacity=capacity)
            for rank, mem in enumerate(ranked, start=1):
                ChurnScore.objects.create(run=run, branch="Hamra", week_start=run.week_start, member=mem, rank=rank,
                                          score=90 - rank, level="High", method="rules")
            return run

        def call(run, mem, outcome):
            RetentionCall.objects.create(member=mem, branch="Hamra", week_start=run.week_start, outcome=outcome)

        # Week A (60 days ago): m1, m2 listed; m3-m5 below the cap.
        a = week(60, [m[1], m[2], m[3], m[4], m[5]])
        call(a, m[1], "saved")
        call(a, m[2], "no_answer")
        # Week B (45 days ago): m2, m3 listed; m5, m6 below.
        week(45, [m[2], m[3], m[5], m[6]])
        # This week: m2, m5 listed; m6 below. m2 reached.
        current = week(0, [m[2], m[5], m[6]])
        call(current, m[2], "reached")
        # Cancellations: m1 10 days after week A, m4 20 days after A, m3 30 days
        # after A (= 15 days after B), so m3 counts in both weeks' windows.
        cancel(m[1], 50)
        cancel(m[4], 40)
        cancel(m[3], 30)

    def test_not_enough_data_yet_by_default(self):
        result = branch_accuracy("Hamra")
        self.assertFalse(result["precision"]["enough"])
        self.assertIsNone(result["precision"]["precisionAtN"])
        self.assertEqual(result["precision"]["finishedWeeks"], 2)

    def test_precision_at_n_on_a_known_dataset(self):
        with mock.patch.object(config, "ACCURACY_MIN_LISTED", 4):
            result = branch_accuracy("Hamra")
        p = result["precision"]
        self.assertTrue(p["enough"])
        # Weeks A and B are finished (30+ days since the list); this week isn't.
        self.assertEqual(p["finishedWeeks"], 2)
        self.assertEqual((p["listed"], p["listedCancelled"]), (4, 2))
        self.assertEqual(p["precisionAtN"], 0.5)
        # Below the cap: m3-m5 in A (m3 and m4 left within 30 days), m5, m6 in B.
        self.assertEqual((p["others"], p["othersCancelled"]), (5, 2))
        self.assertEqual(p["othersRate"], 0.4)
        self.assertEqual(p["lift"], 1.2)
        # Of the listed members staff actually reached (m1 in week A), 1 left anyway.
        self.assertEqual((p["contacted"], p["contactedCancelled"]), (1, 1))

    def test_this_week_and_all_weeks_counts(self):
        result = branch_accuracy("Hamra")
        self.assertEqual(result["thisWeek"]["capacity"], 2)
        self.assertEqual(result["thisWeek"]["listed"], 2)
        self.assertEqual(result["thisWeek"]["contacted"], 1)
        self.assertEqual(result["thisWeek"]["toCall"], 1)
        self.assertEqual(result["allWeeks"]["weeks"], 3)
        self.assertEqual(result["allWeeks"]["listed"], 6)
        self.assertEqual(result["allWeeks"]["contacted"], 2)
        self.assertEqual(result["allWeeks"]["saved"], 1)
        self.assertEqual(result["allWeeks"]["noAnswer"], 1)

    def test_no_lists_yet(self):
        self.assertIsNone(branch_accuracy("Zalka"))
