from datetime import datetime, timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from checkins.models import CheckIn
from classes.models import PTSession
from classes.tests import PASSWORD, _coach, _member, _member_login, _staff
from feedback.models import CoachFeedback
from notifications.models import MemberNotification, StaffNotification

from . import rules
from .models import BranchSurvey, Complaint

# Every test runs at noon on 15 November 2026, Beirut time.
NOW = timezone.make_aware(datetime(2026, 11, 15, 12, 0))
FEEDBACK = "manage_member_feedback"
SURVEY = {"branch": "Hamra", "nps": 9, "cleanliness": 4, "equipment": 2, "comment": "Squat racks always taken."}
COMPLAINT = {"branch": "Hamra", "category": "Equipment", "subject": "Treadmill 3 is broken",
             "description": "The belt stops after a minute, since Monday."}


def _visit(member, branch="Hamra", when=None, result=CheckIn.Result.ALLOWED):
    check_in = CheckIn.objects.create(member=member, result=result, branch=branch)
    if when:
        CheckIn.objects.filter(pk=check_in.pk).update(checked_in_at=when)
    return check_in


class FrozenClock(TestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=NOW)
        self.clock = patcher.start()
        self.addCleanup(patcher.stop)

    def at(self, moment):
        self.clock.return_value = moment


# The member's side: rating their branch and reporting problems.
class MemberSideTests(FrozenClock):
    @classmethod
    def setUpTestData(cls):
        cls.bm = _staff("bm", [FEEDBACK, "manage_members"], branch="Hamra")
        cls.gm = _staff("gm", [FEEDBACK, "view_all_branches"], job_title=StaffAccount.JobTitle.GENERAL_MANAGER)
        cls.desk = _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        cls.jnah_bm = _staff("jnah_bm", [FEEDBACK], branch="Jnah")
        cls.lea = _member("Lea Haddad", "lea")
        cls.sami = _member("Sami Khoury", "sami")

    def setUp(self):
        super().setUp()
        _member_login(self.client, "lea")

    def survey(self, **changes):
        return self.client.post("/api/members/me/branch-feedback/surveys", {**SURVEY, **changes}, content_type="application/json")

    def complain(self, **changes):
        return self.client.post("/api/members/me/complaints", {**COMPLAINT, **changes}, content_type="application/json")

    def test_only_recent_visitors_can_rate_a_branch_once_a_month(self):
        self.assertEqual(self.client.get("/api/members/me/branch-feedback").json()["surveys"], [])
        self.assertEqual(self.survey().status_code, 403)
        _visit(self.lea, result=CheckIn.Result.DENIED)                      # turned away at the door: not a visit
        _visit(self.lea, when=NOW - timedelta(days=61))                      # too long ago
        self.assertEqual(self.survey().status_code, 403)

        _visit(self.lea, when=NOW - timedelta(days=3))
        [status] = self.client.get("/api/members/me/branch-feedback").json()["surveys"]
        self.assertEqual((status["branch"], status["canSurvey"]), ("Hamra", True))
        res = self.survey()
        self.assertEqual(res.status_code, 201, res.content)
        survey = BranchSurvey.objects.get()
        self.assertEqual((survey.nps, survey.equipment, survey.staff, survey.anonymous), (9, 2, None, False))
        [status] = res.json()["surveys"]
        self.assertEqual((status["canSurvey"], status["nextOn"]), (False, "2026-12-15"))

        res = self.survey()
        self.assertEqual(res.status_code, 409)
        self.assertIn("15 Dec 2026", res.json()["error"])
        self.at(NOW + timedelta(days=30))
        _member_login(self.client, "lea")      # the old sign-in has expired by then
        _visit(self.lea)
        self.assertEqual(self.survey(nps=7).status_code, 201)

    def test_a_visit_to_another_branch_lets_you_rate_that_one(self):
        _visit(self.lea, branch="Jnah")
        self.assertEqual(self.survey().status_code, 403)
        self.assertEqual(self.survey(branch="Jnah").status_code, 201)

    def test_what_a_survey_needs(self):
        _visit(self.lea)
        for changes, field in [({"nps": None}, "nps"), ({"nps": 11}, "nps"), ({"nps": -1}, "nps"),
                               ({"cleanliness": 0}, "cleanliness"), ({"equipment": 6}, "equipment"),
                               ({"comment": "x" * 1001}, "comment"), ({"branch": "Mars"}, "branch"),
                               ({"cleanliness": None, "equipment": None, "comment": ""}, "non_field_errors")]:
            body = {**SURVEY, **changes}
            body = {k: v for k, v in body.items() if not (k == "nps" and v is None)}
            res = self.client.post("/api/members/me/branch-feedback/surveys", body, content_type="application/json")
            self.assertEqual(res.status_code, 400, changes)
            self.assertIn(field, res.json()["error"], changes)
        self.assertFalse(BranchSurvey.objects.exists())

    def test_a_complaint_reaches_the_branchs_managers(self):
        res = self.complain()                      # their own branch: no visit needed (billing, for one)
        self.assertEqual(res.status_code, 201, res.content)
        [complaint] = res.json()["complaints"]
        self.assertEqual((complaint["status"], complaint["urgent"], complaint["categoryLabel"]),
                         ("Open", False, "Broken or missing equipment"))
        self.assertNotIn("member", complaint)
        notified = set(StaffNotification.objects.values_list("recipient__username", flat=True))
        self.assertEqual(notified, {"bm"})     # not the desk (no permission), not other branches

    def test_safety_complaints_are_urgent_and_go_to_the_general_manager_too(self):
        res = self.complain(category="Safety", subject="Loose cable by the stairs")
        self.assertTrue(res.json()["complaints"][0]["urgent"])
        notified = set(StaffNotification.objects.values_list("recipient__username", flat=True))
        self.assertEqual(notified, {"bm", "gm"})
        self.assertTrue(StaffNotification.objects.filter(title__startswith="Urgent: ").exists())

    def test_which_branches_and_what_a_complaint_needs(self):
        self.assertEqual(self.complain(branch="Jnah").status_code, 400)
        _visit(self.lea, branch="Jnah")
        self.assertEqual(self.complain(branch="Jnah").status_code, 201)
        for changes, field in [({"subject": "Bad"}, "subject"), ({"description": "Too short"}, "description"),
                               ({"category": "Music"}, "category"), ({"description": "x" * 2001}, "description")]:
            res = self.complain(**changes)
            self.assertEqual(res.status_code, 400, changes)
            self.assertIn(field, res.json()["error"], changes)

    def test_at_most_five_open_complaints(self):
        for _ in range(5):
            self.complain()
        self.assertEqual(self.complain().status_code, 409)
        Complaint.objects.filter(pk=Complaint.objects.first().pk).update(status=Complaint.Status.RESOLVED, resolved_at=NOW)
        self.assertEqual(self.complain().status_code, 201)

    def test_replying_and_reopening(self):
        complaint_id = self.complain().json()["complaints"][0]["id"]
        res = self.client.post(f"/api/members/me/complaints/{complaint_id}/messages", {"body": "Still broken today."},
                               content_type="application/json")
        self.assertEqual(res.json()["complaints"][0]["messages"][0]["body"], "Still broken today.")
        Complaint.objects.filter(pk=complaint_id).update(status=Complaint.Status.RESOLVED, resolved_at=NOW - timedelta(days=3))
        res = self.client.post(f"/api/members/me/complaints/{complaint_id}/messages", {"body": "It broke again."},
                               content_type="application/json")
        self.assertEqual(res.json()["complaints"][0]["status"], "Open")
        Complaint.objects.filter(pk=complaint_id).update(status=Complaint.Status.RESOLVED, resolved_at=NOW - timedelta(days=15))
        res = self.client.post(f"/api/members/me/complaints/{complaint_id}/messages", {"body": "Again!"},
                               content_type="application/json")
        self.assertEqual(res.status_code, 409)

    def test_nobody_touches_someone_elses_complaint(self):
        theirs = Complaint.objects.create(member=self.sami, **COMPLAINT)
        res = self.client.post(f"/api/members/me/complaints/{theirs.id}/messages", {"body": "Hi"}, content_type="application/json")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.client.get("/api/members/me/branch-feedback").json()["complaints"], [])

    def test_members_only(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/members/me/branch-feedback").status_code, 401)
        staff_login(self.client, "bm", PASSWORD)
        self.assertEqual(self.complain().status_code, 401)
        self.assertEqual(self.survey().status_code, 401)

    def test_surveys_and_complaints_are_exported_then_anonymized_on_erase(self):
        _visit(self.lea)
        self.survey(anonymous=True)
        self.complain()
        export = self.client.get("/api/members/me/export").content
        self.assertIn(b"Squat racks always taken.", export)
        self.assertIn(b"Treadmill 3 is broken", export)
        res = self.client.post("/api/members/me/delete", {"password": PASSWORD, "confirm": "DELETE"}, content_type="application/json")
        self.assertEqual(res.status_code, 200)
        survey, complaint = BranchSurvey.objects.get(), Complaint.objects.get()
        self.assertEqual((survey.member, survey.comment, survey.nps), (None, "", 9))   # the score still counts
        self.assertEqual((complaint.member, complaint.subject, complaint.description), (None, "[removed]", "[removed]"))


# User story: "As a branch manager, I want to view member feedback and
# complaints specific to my branch, so that I can address local service
# issues directly rather than waiting on a company wide report."
class ManagerSideTests(FrozenClock):
    @classmethod
    def setUpTestData(cls):
        cls.bm = _staff("bm", [FEEDBACK, "manage_members"], branch="Hamra")
        _staff("gm", [FEEDBACK, "view_all_branches"], job_title=StaffAccount.JobTitle.GENERAL_MANAGER)
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        cls.hadi = _coach("hadi")
        cls.lea = _member("Lea Haddad", "lea")
        cls.sami = _member("Sami Khoury", "sami")

    def setUp(self):
        super().setUp()
        staff_login(self.client, "bm", PASSWORD)

    def survey(self, nps, when=NOW, branch="Hamra", member=None, **fields):
        s = BranchSurvey.objects.create(member=member or self.lea, branch=branch, nps=nps, **fields)
        BranchSurvey.objects.filter(pk=s.pk).update(created_at=when)
        return s

    def complaint(self, when=NOW, **fields):
        c = Complaint.objects.create(member=self.lea, **{**COMPLAINT, **fields})
        Complaint.objects.filter(pk=c.pk).update(created_at=when)
        c.refresh_from_db()
        return c

    def summary(self, **params):
        return self.client.get("/api/branch-feedback/summary", params)

    def test_the_months_scores_against_last_month(self):
        for score, clean in [(10, 5), (9, 4), (8, None), (6, 2), (3, 1)]:
            self.survey(score, cleanliness=clean, equipment=3)
        self.survey(10, when=timezone.make_aware(datetime(2026, 10, 20, 9, 0)), cleanliness=5, equipment=4)
        self.survey(2, branch="Jnah")                                    # another branch: not counted
        body = self.summary().json()
        self.assertEqual((body["branch"], body["period"]["key"]), ("Hamra", "2026-11"))
        self.assertEqual(body["nps"], {"score": 0, "responses": 5, "promoters": 2, "passives": 1, "detractors": 2,
                                       "previousScore": 100, "previousResponses": 1})
        areas = {a["key"]: a for a in body["areas"]}
        self.assertEqual((areas["cleanliness"]["average"], areas["cleanliness"]["count"], areas["cleanliness"]["change"]), (3.0, 4, -2.0))
        self.assertEqual((areas["staff"]["average"], areas["staff"]["count"]), (None, 0))
        self.assertEqual(body["weakestArea"], "cleanliness")
        self.assertEqual([t["period"] for t in body["trend"]], ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"])
        self.assertEqual([t["nps"] for t in body["trend"][-2:]], [100, 0])

    def test_comments_hide_anonymous_members(self):
        self.survey(4, comment="Showers are cold.", anonymous=True)
        self.survey(9, member=self.sami, comment="Great staff!", when=NOW - timedelta(hours=1))
        self.survey(7)                                                   # no comment: not listed
        comments = self.summary().json()["comments"]
        self.assertEqual([(c["comment"], c["member"]) for c in comments],
                         [("Showers are cold.", None), ("Great staff!", {"id": self.sami.id, "name": "Sami Khoury"})])
        self.assertNotIn("Lea", str(comments))

    def test_coach_ratings_for_the_branch(self):
        starts = NOW - timedelta(days=2)
        session = PTSession.objects.create(coach=self.hadi, member=self.lea, branch="Hamra", starts_at=starts, ends_at=starts + timedelta(hours=1))
        CoachFeedback.objects.create(member=self.lea, coach=self.hadi, pt_session=session, branch="Hamra", session_name="PT",
                                     session_starts_at=starts, session_ends_at=starts + timedelta(hours=1), rating=4)
        self.assertEqual(self.summary().json()["coachRatings"], [{"coachId": self.hadi.id, "name": "Hadi", "average": 4.0, "count": 1}])

    def test_branch_managers_see_only_their_branch(self):
        self.assertEqual(self.summary(branch="Jnah").status_code, 403)
        self.assertEqual(self.client.get("/api/branch-feedback/complaints", {"branch": "Jnah"}).status_code, 403)
        jnah = self.complaint(branch="Jnah")
        self.assertEqual(self.client.get(f"/api/branch-feedback/complaints/{jnah.id}").status_code, 403)
        staff_login(self.client, "gm", PASSWORD)
        self.assertEqual(self.summary(branch="Jnah").json()["branch"], "Jnah")
        self.assertEqual(self.client.get(f"/api/branch-feedback/complaints/{jnah.id}").status_code, 200)
        for username in ("desk", "hadi"):
            staff_login(self.client, username, PASSWORD)
            self.assertEqual(self.summary().status_code, 403, username)
        self.client.logout()
        self.assertEqual(self.summary().status_code, 401)

    def test_a_bad_period(self):
        for bad in ("2026-12", "nov", "2024-01"):
            self.assertEqual(self.summary(period=bad).status_code, 400, bad)
        self.assertEqual(self.summary(period="2026-10").json()["period"]["label"], "October 2026")

    def test_the_queue_puts_urgent_then_oldest_first_and_flags_overdue(self):
        newer = self.complaint(when=NOW - timedelta(hours=2), subject="Music too loud")
        older = self.complaint(when=NOW - timedelta(hours=50), subject="Lockers jammed")
        urgent = self.complaint(when=NOW - timedelta(hours=1), category="Safety", urgent=True, subject="Wet floor, no sign")
        done = self.complaint(subject="Old issue", status=Complaint.Status.RESOLVED)
        res = self.client.get("/api/branch-feedback/complaints").json()["results"]
        self.assertEqual([c["id"] for c in res], [urgent.id, older.id, newer.id])
        self.assertEqual([c["overdue"] for c in res], [False, True, False])
        self.assertEqual(res[1]["member"]["name"], "Lea Haddad")
        resolved = self.client.get("/api/branch-feedback/complaints", {"status": "resolved"}).json()["results"]
        self.assertEqual([c["id"] for c in resolved], [done.id])
        safety = self.client.get("/api/branch-feedback/complaints", {"status": "all", "category": "Safety"}).json()["results"]
        self.assertEqual([c["id"] for c in safety], [urgent.id])
        self.assertEqual(self.client.get("/api/branch-feedback/complaints", {"status": "late"}).status_code, 400)
        counts = self.summary().json()["complaints"]
        self.assertEqual((counts["open"], counts["overdue"], counts["urgentOpen"], counts["received"]), (3, 1, 1, 4))

    def test_a_reply_reaches_the_member_and_starts_the_case(self):
        complaint = self.complaint(when=NOW - timedelta(hours=5))
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(f"/api/branch-feedback/complaints/{complaint.id}/messages",
                                   {"body": "Sorry - a technician comes Thursday."}, content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertEqual((body["status"], body["firstResponseHours"], body["overdue"]), ("In progress", 5.0, False))
        note = MemberNotification.objects.get(recipient=self.lea)
        self.assertEqual(note.kind, MemberNotification.Kind.COMPLAINT_UPDATE)
        self.assertIn("technician comes Thursday", note.message)
        self.assertEqual(len(mail.outbox), 1)

    def test_internal_notes_stay_between_staff(self):
        complaint = self.complaint()
        res = self.client.post(f"/api/branch-feedback/complaints/{complaint.id}/messages",
                               {"body": "Part ordered, $120.", "internal": True}, content_type="application/json")
        self.assertEqual((res.json()["status"], res.json()["messages"][0]["internal"]), ("Open", True))
        self.assertFalse(MemberNotification.objects.exists())
        complaint.refresh_from_db()
        self.assertIsNone(complaint.first_response_at)               # a note isn't an answer
        _member_login(self.client, "lea")
        mine = self.client.get("/api/members/me/branch-feedback").json()["complaints"][0]
        self.assertEqual(mine["messages"], [])

    def test_resolving_needs_an_answer_to_the_member(self):
        complaint = self.complaint()
        url = f"/api/branch-feedback/complaints/{complaint.id}"
        res = self.client.patch(url, {"status": "Resolved"}, content_type="application/json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("message", res.json()["error"])
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.patch(url, {"status": "Resolved", "message": "Treadmill repaired this morning."},
                                    content_type="application/json")
        body = res.json()
        self.assertEqual((body["status"], body["resolvedBy"]), ("Resolved", "Bm"))
        self.assertEqual([m["body"] for m in body["messages"]], ["Treadmill repaired this morning."])
        kinds = list(MemberNotification.objects.order_by("id").values_list("title", flat=True))
        self.assertEqual(kinds, ["Reply to your complaint: Treadmill 3 is broken", "Resolved: Treadmill 3 is broken"])
        entry = AuditLog.objects.get(action=AuditLog.Action.COMPLAINT_STATUS_CHANGED)
        self.assertEqual(entry.details, {"complaintId": complaint.id, "from": "Open", "to": "Resolved"})
        # Resolved: no more replies until it's reopened.
        res = self.client.post(f"{url}/messages", {"body": "One more thing"}, content_type="application/json")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(self.client.patch(url, {"status": "Open"}, content_type="application/json").json()["status"], "Open")
        self.assertEqual(self.client.patch(url, {"status": "Open"}, content_type="application/json").status_code, 400)

    def test_a_complaint_from_an_erased_member_takes_internal_notes_only(self):
        complaint = self.complaint()
        Complaint.objects.filter(pk=complaint.pk).update(member=None)
        url = f"/api/branch-feedback/complaints/{complaint.id}/messages"
        self.assertEqual(self.client.post(url, {"body": "Hello?"}, content_type="application/json").status_code, 409)
        self.assertEqual(self.client.post(url, {"body": "Closing.", "internal": True}, content_type="application/json").status_code, 201)

    def test_nps(self):
        self.assertEqual(rules.nps([])["score"], None)
        self.assertEqual(rules.nps([10, 10, 9])["score"], 100)
        self.assertEqual(rules.nps([0, 6, 7, 8])["score"], -50)
