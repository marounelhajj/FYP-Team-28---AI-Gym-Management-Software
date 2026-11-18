from datetime import datetime, timedelta

from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from classes.models import PTSession
from classes.tests import PASSWORD, _coach, _member, _staff
from feedback.models import CoachFeedback
from members.models import Member

from .models import BranchSurvey, Complaint
from .tests import COMPLAINT, FEEDBACK, NOW, FrozenClock

# SCRUM-23: the general manager's view of feedback across every branch.
# Every test runs at noon on 15 November 2026 (FrozenClock).


class OverviewTests(FrozenClock):
    @classmethod
    def setUpTestData(cls):
        cls.gm = _staff("gm", [FEEDBACK, "view_all_branches"], job_title=StaffAccount.JobTitle.GENERAL_MANAGER)
        cls.bm = _staff("bm", [FEEDBACK], branch="Hamra")
        cls.hadi = _coach("hadi")
        cls.lea = _member("Lea Haddad", "lea")
        cls.sami = _member("Sami Khoury", "sami")

    def setUp(self):
        super().setUp()
        staff_login(self.client, "gm", PASSWORD)

    def survey(self, branch, nps, when=NOW, member=None, **fields):
        s = BranchSurvey.objects.create(member=member or self.lea, branch=branch, nps=nps, **fields)
        BranchSurvey.objects.filter(pk=s.pk).update(created_at=when)
        return s

    def complaint(self, branch, category, when=NOW, **fields):
        c = Complaint.objects.create(member=self.lea, **{**COMPLAINT, "branch": branch, "category": category, **fields})
        Complaint.objects.filter(pk=c.pk).update(created_at=when)
        return c

    def overview(self, **params):
        return self.client.get("/api/branch-feedback/overview", params)

    def test_every_branch_side_by_side(self):
        self.survey("Hamra", 10, cleanliness=5)
        self.survey("Hamra", 9, cleanliness=4)
        self.survey("Hamra", 8, when=timezone.make_aware(datetime(2026, 10, 10, 9, 0)))
        self.survey("Jnah", 3, cleanliness=2)
        body = self.overview().json()
        self.assertEqual(body["period"]["key"], "2026-11")
        rows = {r["branch"]: r for r in body["branches"]}
        self.assertEqual(list(rows), list(Member.Branch.values))
        self.assertEqual((rows["Hamra"]["nps"], rows["Hamra"]["responses"], rows["Hamra"]["npsChange"]), (100, 2, 100))
        self.assertEqual(rows["Hamra"]["areas"]["cleanliness"], {"average": 4.5, "count": 2})
        self.assertEqual((rows["Jnah"]["nps"], rows["Jnah"]["weakestArea"]), (-100, "cleanliness"))
        # A branch nobody rated is still listed, empty.
        self.assertEqual((rows["Zalka"]["nps"], rows["Zalka"]["responses"]), (None, 0))
        # The company line counts every response this month.
        self.assertEqual((body["company"]["responses"], body["company"]["nps"]), (3, 33))
        self.assertEqual(body["company"]["areas"]["cleanliness"]["average"], 3.7)

    def test_a_category_at_several_branches_is_recurring(self):
        self.complaint("Hamra", "Equipment")
        self.complaint("Jnah", "Equipment")
        self.complaint("Hamra", "Billing")
        self.complaint("Hamra", "Equipment", when=NOW - timedelta(days=40))      # last month: not counted
        issues = {c["category"]: c for c in self.overview().json()["recurringComplaints"]}
        self.assertTrue(issues["Equipment"]["recurring"])
        self.assertEqual(issues["Equipment"]["total"], 2)
        self.assertEqual([b["branch"] for b in issues["Equipment"]["branches"]], ["Hamra", "Jnah"])
        self.assertFalse(issues["Billing"]["recurring"])

    def test_a_category_reported_often_at_one_branch_is_recurring_too(self):
        for _ in range(3):
            self.complaint("Jnah", "Crowding")
        self.complaint("Jnah", "Staff")
        issues = self.overview().json()["recurringComplaints"]
        self.assertEqual([(c["category"], c["recurring"]) for c in issues], [("Crowding", True), ("Staff", False)])

    def test_weak_service_areas_need_enough_ratings(self):
        for member in (self.lea, self.sami):
            self.survey("Jnah", 5, member=member, equipment=2)
        body = self.overview().json()
        self.assertEqual(body["weakAreas"], [])                     # 2 ratings: not a trend yet
        self.survey("Jnah", 5, equipment=1)
        self.survey("Hamra", 8, equipment=2)                            # only one rating at Hamra
        [weak] = self.overview().json()["weakAreas"]
        self.assertEqual((weak["key"], weak["branches"]), ("equipment", [{"branch": "Jnah", "average": 1.7}]))

    def test_complaint_counts_per_branch(self):
        self.complaint("Hamra", "Equipment", when=NOW - timedelta(hours=60))          # overdue
        escalated = self.complaint("Hamra", "Billing")
        Complaint.objects.filter(pk=escalated.pk).update(escalated_at=NOW, escalated_by=self.bm)
        self.complaint("Jnah", "Staff", status=Complaint.Status.RESOLVED, resolved_at=NOW)
        body = self.overview().json()
        rows = {r["branch"]: r for r in body["branches"]}
        self.assertEqual(rows["Hamra"]["complaints"],
                         {"received": 2, "resolved": 0, "open": 2, "inProgress": 0, "overdue": 1, "escalatedOpen": 1})
        self.assertEqual(rows["Jnah"]["complaints"]["resolved"], 1)
        company = body["company"]
        self.assertEqual((company["complaints"], company["openComplaints"], company["overdue"], company["escalatedOpen"]), (3, 2, 1, 1))

    def test_what_members_wrote_newest_first_and_anonymous_stays_so(self):
        self.survey("Hamra", 9, comment="Love the new racks.", when=NOW - timedelta(days=3))
        self.survey("Jnah", 4, member=self.sami, comment="Too crowded.", anonymous=True, when=NOW - timedelta(days=1))
        self.survey("Jnah", 7, when=NOW - timedelta(hours=5))                            # no comment: not in the feed
        self.complaint("Jnah", "Cleanliness", subject="Showers are cold", when=NOW - timedelta(hours=2))
        starts = NOW - timedelta(days=2)
        session = PTSession.objects.create(coach=self.hadi, member=self.lea, branch="Hamra", starts_at=starts,
                                           ends_at=starts + timedelta(hours=1))
        rating = CoachFeedback.objects.create(member=self.lea, coach=self.hadi, pt_session=session, branch="Hamra",
                                              session_name="Private training", session_starts_at=starts,
                                              session_ends_at=starts + timedelta(hours=1), rating=5, comment="Great form tips.")
        CoachFeedback.objects.filter(pk=rating.pk).update(created_at=NOW - timedelta(hours=20))
        feed = self.overview().json()["feed"]
        self.assertEqual([(i["kind"], i["text"]) for i in feed], [
            ("complaint", "Showers are cold"), ("coach", "Great form tips."),
            ("survey", "Too crowded."), ("survey", "Love the new racks."),
        ])
        self.assertIsNone(feed[2]["who"])
        self.assertEqual(feed[3]["who"], "Lea Haddad")
        self.assertEqual(feed[1]["about"], "Hadi · Private training")

        rows = {r["branch"]: r for r in self.overview().json()["branches"]}
        self.assertEqual((rows["Hamra"]["coachAverage"], rows["Hamra"]["coachRatings"]), (5.0, 1))

    def test_another_month(self):
        self.survey("Hamra", 2, when=timezone.make_aware(datetime(2026, 10, 3, 9, 0)))
        body = self.overview(period="2026-10").json()
        self.assertEqual(body["period"]["label"], "October 2026")
        self.assertEqual({r["branch"]: r["nps"] for r in body["branches"]}["Hamra"], -100)
        self.assertEqual(self.overview(period="soon").status_code, 400)

    def test_only_roles_that_see_every_branch(self):
        self.client.post("/api/auth/logout")
        self.assertEqual(self.overview().status_code, 401)
        staff_login(self.client, "bm", PASSWORD)
        self.assertEqual(self.overview().status_code, 403)
        self.client.post("/api/auth/logout")
        _staff("viewer", ["view_all_branches"], job_title=StaffAccount.JobTitle.GENERAL_MANAGER)
        staff_login(self.client, "viewer", PASSWORD)
        self.assertEqual(self.overview().status_code, 403)
