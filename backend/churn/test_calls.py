from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from members.models import Member
from members.privacy import anonymize_member, build_export
from training.models import TrainingEvent

from .features import week_start
from .models import ChurnScore, RetentionCall
from .scoring import refresh_branch
from .testing import PASSWORD, member, regular, staff

DESK = ["view_at_risk_members", "log_retention_calls"]


# User story (SCRUM-68): "As a receptionist, I want to log the outcome of a
# retention call on an at-risk member's record, so that the team knows who
# has been contacted and the system captures whether the outreach worked."
class RetentionCallTests(TestCase):
    def setUp(self):
        self.desk = staff("desk", DESK, branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        staff("viewer", ["view_at_risk_members"], branch="Hamra")
        staff("jnahdesk", DESK, branch="Jnah", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        self.rana = member("Rana Fading", expires_in=12)
        regular(self.rana, per_week=3, recent_per_week=1)
        self.omar = member("Omar Steady")
        regular(self.omar, per_week=3)
        refresh_branch("Hamra")
        staff_login(self.client, "desk", PASSWORD)

    def log(self, outcome, who=None, **extra):
        body = {"memberId": (who or self.rana).pk, "outcome": outcome, **extra}
        return self.client.post("/api/churn/calls", body, content_type="application/json")

    def listed(self):
        body = self.client.get("/api/churn/at-risk").json()
        return [m["memberId"] for m in body["members"]], [m["memberId"] for m in body["contacted"]]

    # AC: outcome options include reached / no answer / saved / cancelled anyway.
    def test_each_outcome_can_be_logged(self):
        for outcome in ["reached", "no_answer", "saved", "cancelled_anyway"]:
            res = self.log(outcome)
            self.assertEqual(res.status_code, 201, res.content)
            self.assertEqual(res.json()["outcome"], outcome)
        self.assertEqual(RetentionCall.objects.count(), 4)
        labels = [label for _, label in RetentionCall.Outcome.choices]
        self.assertEqual(labels, ["Reached", "No answer", "Saved", "Cancelled anyway"])

    def test_call_keeps_note_follow_up_staff_and_the_list_entry(self):
        follow_up = timezone.localdate() + timedelta(days=7)
        res = self.log("reached", note="Busy with exams, back next month", followUpOn=follow_up.isoformat())
        self.assertEqual(res.status_code, 201, res.content)
        call = RetentionCall.objects.get()
        entry = ChurnScore.objects.get(member=self.rana)
        self.assertEqual(call.note, "Busy with exams, back next month")
        self.assertEqual(call.follow_up_on, follow_up)
        self.assertEqual(call.called_by, self.desk)
        self.assertEqual(call.called_by_name, "Desk")
        self.assertEqual((call.score, call.level, call.rank, call.method), (entry.score, entry.level, entry.rank, "rules"))
        self.assertEqual(call.reasons[0]["text"], "Visits dropped from 3 a week to 1 a week")

    def test_bad_input(self):
        self.assertEqual(self.log("maybe").status_code, 400)
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        self.assertIn("followUpOn", self.log("reached", followUpOn=yesterday).json()["error"])
        self.assertIn("note", self.log("reached", note="x" * 501).json()["error"])
        self.assertEqual(self.client.post("/api/churn/calls", {"memberId": 999999, "outcome": "saved"},
                                          content_type="application/json").status_code, 404)
        self.assertFalse(RetentionCall.objects.exists())

    def test_member_not_on_this_weeks_list(self):
        ChurnScore.objects.filter(member=self.rana).delete()
        res = self.log("reached")
        self.assertEqual(res.status_code, 400)
        self.assertIn("isn't on this week's at-risk list", res.json()["error"])

    # AC: contacted members drop off the active call list.
    def test_contacted_members_drop_off_the_active_list(self):
        for outcome in ["reached", "saved", "cancelled_anyway"]:
            RetentionCall.objects.all().delete()
            self.assertIn(self.rana.pk, self.listed()[0])
            self.log(outcome)
            active, done = self.listed()
            self.assertNotIn(self.rana.pk, active, outcome)
            self.assertIn(self.rana.pk, done, outcome)
            self.assertIn(self.omar.pk, active)

    # "No answer" keeps them on the list until the end of the week, for a retry.
    def test_no_answer_stays_on_the_list_for_a_retry(self):
        self.log("no_answer")
        active, done = self.listed()
        self.assertIn(self.rana.pk, active)
        self.assertNotIn(self.rana.pk, done)
        row = next(m for m in self.client.get("/api/churn/at-risk").json()["members"] if m["memberId"] == self.rana.pk)
        self.assertEqual(row["callsThisWeek"][0]["outcome"], "no_answer")
        # The retry gets through.
        self.assertEqual(self.log("reached").status_code, 201)
        self.assertNotIn(self.rana.pk, self.listed()[0])

    def test_contacted_last_week_is_back_on_next_weeks_list(self):
        self.log("reached")
        next_monday = week_start(timezone.localdate()) + timedelta(days=7)
        with mock.patch("django.utils.timezone.localdate", return_value=next_monday):
            refresh_branch("Hamra")
            self.assertIn(self.rana.pk, self.listed()[0])

    # AC: logged calls are visible on the member record.
    def test_call_history_on_the_member_record(self):
        self.log("no_answer")
        self.log("saved", note="Renewing on Friday")
        res = self.client.get(f"/api/churn/members/{self.rana.pk}/calls")
        self.assertEqual(res.status_code, 200, res.content)
        calls = res.json()["calls"]
        self.assertEqual([c["outcomeLabel"] for c in calls], ["Saved", "No answer"])
        self.assertEqual(calls[0]["calledBy"], "Desk")
        self.assertEqual(calls[0]["note"], "Renewing on Friday")
        self.assertIsNotNone(calls[0]["calledAt"])

    # AC: outcomes are stored as labelled data for later model training.
    def test_training_event_written_with_score_reasons_and_method(self):
        self.log("saved", note="private words")
        event = TrainingEvent.objects.get(event_type=TrainingEvent.EventType.RETENTION_CALL)
        entry = ChurnScore.objects.get(member=self.rana)
        self.assertEqual(event.member, self.rana)
        self.assertEqual(event.branch, "Hamra")
        self.assertEqual(event.payload["outcome"], "saved")
        self.assertEqual(event.payload["score"], entry.score)
        self.assertEqual(event.payload["method"], "rules")
        self.assertEqual(event.payload["reasons"], [r["feature"] for r in entry.reasons])
        self.assertNotIn("private words", str(event.payload))

    def test_audit_log_entry(self):
        self.log("cancelled_anyway")
        entry = AuditLog.objects.get(action=AuditLog.Action.RETENTION_CALL_LOGGED)
        self.assertEqual(entry.actor_staff, self.desk)
        self.assertEqual(entry.target_id, str(self.rana.pk))
        self.assertEqual(entry.details["outcome"], "cancelled_anyway")
        self.assertIn("Cancelled anyway", entry.summary)


class RetentionCallPermissionTests(TestCase):
    def setUp(self):
        staff("viewer", ["view_at_risk_members"], branch="Hamra")
        staff("jnahdesk", DESK, branch="Jnah", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        staff("coach", [], branch="Hamra", job_title=StaffAccount.JobTitle.COACH)
        self.rana = member("Rana Fading", expires_in=12)
        regular(self.rana, per_week=3, recent_per_week=1)
        refresh_branch("Hamra")

    def post(self):
        return self.client.post("/api/churn/calls", {"memberId": self.rana.pk, "outcome": "reached"},
                                content_type="application/json")

    def test_not_signed_in(self):
        self.assertEqual(self.post().status_code, 401)

    def test_role_without_log_permission(self):
        staff_login(self.client, "viewer", PASSWORD)
        self.assertEqual(self.post().status_code, 403)
        body = self.client.get("/api/churn/at-risk").json()
        self.assertFalse(body["canLogCalls"])

    def test_other_branch_staff_cannot_log_or_read(self):
        staff_login(self.client, "jnahdesk", PASSWORD)
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.client.get(f"/api/churn/members/{self.rana.pk}/calls").status_code, 403)
        self.assertFalse(RetentionCall.objects.exists())

    def test_coach_cannot_read_call_history(self):
        staff_login(self.client, "coach", PASSWORD)
        self.assertEqual(self.client.get(f"/api/churn/members/{self.rana.pk}/calls").status_code, 403)


# SCRUM-62: call history is in the member's data export and goes with a deletion request.
class RetentionCallPrivacyTests(TestCase):
    def test_export_and_deletion(self):
        desk = staff("desk", DESK, branch="Hamra")
        rana = member("Rana Fading", expires_in=12)
        regular(rana, per_week=3, recent_per_week=1)
        run = refresh_branch("Hamra")
        entry = ChurnScore.objects.get(run=run, member=rana)
        RetentionCall.objects.create(
            member=rana, branch="Hamra", week_start=run.week_start, outcome="saved", note="Renewing Friday",
            called_by=desk, called_by_name=desk.full_name, churn_score=entry, score=entry.score,
            reasons=[{"feature": "attendance_drop", "text": "Visits dropped", "talkingPoint": "Ask"}],
        )
        exported = build_export(rana)["retentionCalls"]
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]["outcome"], "Saved")
        self.assertEqual(exported[0]["note"], "Renewing Friday")
        self.assertEqual(exported[0]["reasonsAtTheTime"], ["Visits dropped"])

        anonymize_member(rana)
        self.assertFalse(RetentionCall.objects.filter(member=rana).exists())
        self.assertFalse(ChurnScore.objects.filter(member=rana).exists())
        self.assertEqual(Member.objects.get(pk=rana.pk).status, Member.Status.CANCELLED)
