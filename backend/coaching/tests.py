from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from classes.models import ClassBooking, PTSession
from classes.rules import local_datetime
from classes.tests import PASSWORD, _book, _class, _coach, _member, _member_login, _staff
from progress.models import BodyMetric, WorkoutEntry
from training.models import TrainingEvent

from . import progress
from .models import ClientGoal, SessionLog

# Every test runs at noon on 15 November 2026, Beirut time.
NOW = timezone.make_aware(datetime(2026, 11, 15, 12, 0))
TODAY = date(2026, 11, 15)

SQUAT = {"exercise": "Squat", "sets": 3, "reps": 5, "weightKg": "80", "rpe": 8}
RUN = {"exercise": "Treadmill", "durationMinutes": 20, "distanceKm": "3.5"}


def _pt(coach, member, day, start="10:00", minutes=60, **extra):
    starts = local_datetime(day, time.fromisoformat(start))
    return PTSession.objects.create(coach=coach, member=member, branch="Hamra", starts_at=starts,
                                    ends_at=starts + timedelta(minutes=minutes), **extra)


class FrozenClock(TestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)


# User story: "As a coach, I want to log client workout sessions and progress
# notes, so that I can track each client's development over time."
class SessionLogTests(FrozenClock):
    @classmethod
    def setUpTestData(cls):
        cls.hadi = _coach("hadi")
        cls.rita = _coach("rita")
        _staff("bm", ["manage_class_schedule", "manage_members"], branch="Hamra")
        cls.lea = _member("Lea Haddad", "lea", days_valid=400)

    def setUp(self):
        super().setUp()
        self.session = _pt(self.hadi, self.lea, date(2026, 11, 14))
        staff_login(self.client, "hadi", PASSWORD)

    def put(self, body, session=None):
        return self.client.put(f"/api/coaching/pt-sessions/{(session or self.session).id}/log", body,
                               content_type="application/json")

    def full_log(self, **changes):
        return {"exercises": [SQUAT, RUN], "subjective": "Slept badly, knee fine.", "objective": "Squat 3x5 @ 80",
                "assessment": "Bracing improving.", "plan": "Add 2.5 kg to squat.", "bodyWeightKg": "72.4",
                "sessionRpe": 7, **changes}

    def test_logging_a_session_with_exercises_and_a_soap_note(self):
        PTSession.objects.filter(pk=self.session.pk).update(attendance=ClassBooking.Attendance.NO_SHOW)
        res = self.put(self.full_log())
        self.assertEqual(res.status_code, 200, res.content)
        log = res.json()["log"]
        self.assertEqual([e["exercise"] for e in log["exercises"]], ["Squat", "Treadmill"])
        squat, run = log["exercises"]
        self.assertEqual((squat["kind"], squat["estimated1rm"], squat["rpe"]), ("strength", "93.3", 8))
        self.assertEqual((run["kind"], run["sets"], run["durationMinutes"], run["estimated1rm"]), ("cardio", None, 20, None))
        self.assertEqual((log["plan"], log["assessment"], log["bodyWeightKg"], log["sessionRpe"]),
                         ("Add 2.5 kg to squat.", "Bracing improving.", "72.4", 7))
        # The coach's word over the check-in match: they were there.
        self.session.refresh_from_db()
        self.assertEqual(self.session.attendance, ClassBooking.Attendance.ATTENDED)
        event = TrainingEvent.objects.get(event_type=TrainingEvent.EventType.SESSION_LOGGED)
        self.assertEqual((event.session_id, event.trainer_id), (f"pt:{self.session.id}", self.hadi.id))
        self.assertEqual(event.payload["exercises"][0], {"exercise": "Squat", "kind": "strength", "sets": 3, "reps": 5,
                                                         "weightKg": "80.0", "durationMinutes": None, "distanceKm": None, "rpe": 8})
        self.assertNotIn("Slept badly", str(event.payload))  # notes never go to the AI log

    def test_saving_again_replaces_the_log(self):
        self.put(self.full_log())
        res = self.put(self.full_log(exercises=[{**SQUAT, "weightKg": "82.5"}], plan="Deload next week."))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(SessionLog.objects.count(), 1)
        log = res.json()["log"]
        self.assertEqual(([e["weightKg"] for e in log["exercises"]], log["plan"]), (["82.5"], "Deload next week."))

    def test_the_form_shows_the_last_plan_and_last_exercises(self):
        earlier = _pt(self.hadi, self.lea, date(2026, 11, 10))
        self.put(self.full_log(plan="Try 85 kg."), session=earlier)
        body = self.client.get(f"/api/coaching/pt-sessions/{self.session.id}/log").json()
        self.assertIsNone(body["log"])
        self.assertTrue(body["canEdit"])
        self.assertEqual((body["previousPlan"]["plan"], body["previousPlan"]["date"]), ("Try 85 kg.", "2026-11-10"))
        self.assertEqual([e["exercise"] for e in body["lastExercises"]], ["Squat", "Treadmill"])
        self.assertIn({"name": "Bench press", "kind": "strength"}, body["exerciseChoices"])

    def test_what_a_log_must_contain(self):
        cases = [
            ({"exercises": [{"exercise": "Squat", "reps": 5}]}, "exercises"),
            ({"exercises": [{"exercise": "Treadmill"}]}, "exercises"),
            ({"exercises": [{**SQUAT, "rpe": 11}]}, "exercises"),
            ({"exercises": [{**SQUAT, "weightKg": "600"}]}, "exercises"),
            ({"exercises": [{**SQUAT, "exercise": "   "}]}, "exercises"),
            ({"exercises": [SQUAT] * 31}, "exercises"),
            ({"plan": "x" * 1001}, "plan"),
            ({"bodyWeightKg": "10", "plan": "ok"}, "bodyWeightKg"),
            ({"sessionRpe": 0, "plan": "ok"}, "sessionRpe"),
            ({}, "non_field_errors"),
            ({"exercises": [], "plan": "   "}, "non_field_errors"),
        ]
        for body, field in cases:
            res = self.put(body)
            self.assertEqual(res.status_code, 400, body)
            self.assertIn(field, res.json()["error"], body)
        self.assertFalse(SessionLog.objects.exists())

    def test_a_note_alone_or_a_free_text_exercise_is_fine(self):
        self.assertEqual(self.put({"subjective": "Felt dizzy, stopped early."}).status_code, 200)
        res = self.put({"exercises": [{"exercise": " Sled  push ", "kind": "cardio", "durationMinutes": 5}]})
        self.assertEqual(res.json()["log"]["exercises"][0]["exercise"], "Sled push")

    def test_when_a_session_can_be_logged(self):
        upcoming = _pt(self.hadi, self.lea, date(2026, 11, 16))
        cancelled = _pt(self.hadi, self.lea, date(2026, 11, 13), status=PTSession.Status.CANCELLED)
        old = _pt(self.hadi, self.lea, date(2026, 11, 7))
        in_progress = _pt(self.hadi, self.lea, TODAY, start="11:30")
        self.assertEqual([self.put({"plan": "x"}, s).status_code for s in (upcoming, cancelled, old)], [409, 409, 409])
        self.assertEqual(self.put({"plan": "Started well."}, in_progress).status_code, 200)
        # Locked, but still readable.
        body = self.client.get(f"/api/coaching/pt-sessions/{old.id}/log").json()
        self.assertEqual((body["canEdit"], body["cannotEditReason"][:21]), (False, "Logs lock 7 days afte"))

    def test_the_lock_applies_to_changing_and_deleting_too(self):
        self.put(self.full_log())
        later = NOW + timedelta(days=8)
        with mock.patch("django.utils.timezone.now", return_value=later):
            self.assertEqual(self.put(self.full_log(plan="Rewritten")).status_code, 409)
            self.assertEqual(self.client.delete(f"/api/coaching/pt-sessions/{self.session.id}/log").status_code, 409)
        self.assertEqual(SessionLog.objects.get().plan, "Add 2.5 kg to squat.")

    def test_deleting_a_log(self):
        self.assertEqual(self.client.delete(f"/api/coaching/pt-sessions/{self.session.id}/log").status_code, 404)
        self.put(self.full_log())
        res = self.client.delete(f"/api/coaching/pt-sessions/{self.session.id}/log")
        self.assertEqual((res.status_code, res.json()["log"]), (200, None))
        self.assertFalse(SessionLog.objects.exists())

    def test_only_the_sessions_own_coach(self):
        theirs = _pt(self.rita, self.lea, date(2026, 11, 14), start="15:00")
        self.assertEqual(self.put({"plan": "x"}, theirs).status_code, 403)
        self.assertEqual(self.client.get(f"/api/coaching/pt-sessions/{theirs.id}/log").status_code, 403)
        self.assertEqual(self.client.get("/api/coaching/pt-sessions/999999/log").status_code, 404)
        staff_login(self.client, "bm", PASSWORD)
        self.assertEqual(self.put({"plan": "x"}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.put({"plan": "x"}).status_code, 401)
        _member_login(self.client, "lea")
        self.assertEqual(self.put({"plan": "x"}).status_code, 401)


class ProgressTests(FrozenClock):
    @classmethod
    def setUpTestData(cls):
        cls.hadi = _coach("hadi")
        cls.rita = _coach("rita")
        cls.omar = _coach("omar")
        cls.lea = _member("Lea Haddad", "lea", days_valid=400)

    def setUp(self):
        super().setUp()
        staff_login(self.client, "hadi", PASSWORD)

    def log(self, coach, day, exercises=(), **fields):
        session = _pt(coach, self.lea, day)
        log = SessionLog.objects.create(session=session, member=self.lea, coach=coach, **fields)
        for i, e in enumerate(exercises):
            log.exercises.create(order=i, kind="strength", **e)
        return log

    def get(self, member=None):
        return self.client.get(f"/api/coaching/clients/{(member or self.lea).id}/progress")

    def test_epley(self):
        self.assertEqual(progress.epley(Decimal("100"), 1), Decimal("100.0"))
        self.assertEqual(progress.epley(Decimal("80"), 5), Decimal("93.3"))
        self.assertIsNone(progress.epley(Decimal("40"), 13))   # too many reps to estimate from
        self.assertIsNone(progress.epley(None, 5))

    def test_strength_combines_coach_and_member_logs_and_flags_records(self):
        self.log(self.hadi, date(2026, 11, 2), [{"exercise": "Squat", "sets": 3, "reps": 5, "weight_kg": Decimal("80")}])
        WorkoutEntry.objects.create(member=self.lea, performed_on=date(2026, 11, 5), exercise="squat", kind="strength",
                                    sets=5, reps=5, weight_kg=Decimal("75"))           # lighter: not a record
        self.log(self.rita, date(2026, 11, 9), [{"exercise": "Squat", "sets": 3, "reps": 3, "weight_kg": Decimal("90")},
                                                {"exercise": "Squat", "sets": 2, "reps": 15, "weight_kg": Decimal("50")}])
        squat = self.get().json()["strength"][0]
        self.assertEqual((squat["exercise"], squat["sessions"], squat["best"], squat["latest"], squat["change"]),
                         ("Squat", 3, "99.0", "99.0", "5.7"))
        self.assertEqual([(p["date"], p["e1rm"], p["record"], p["source"]) for p in squat["points"]], [
            ("2026-11-02", "93.3", False, "coach"), ("2026-11-05", "87.5", False, "self"), ("2026-11-09", "99.0", True, "coach"),
        ])
        # Every set counts towards volume, even the high-rep one that can't estimate a max.
        self.assertEqual(squat["points"][2]["volume"], "2310.0")
        self.assertEqual(squat["points"][2]["bestSet"], "3 × 3 @ 90 kg")

    def test_body_weight_from_both_sources_the_coach_wins_on_the_same_day(self):
        BodyMetric.objects.create(member=self.lea, measured_on=date(2026, 11, 2), weight_kg=Decimal("74.0"))
        BodyMetric.objects.create(member=self.lea, measured_on=date(2026, 11, 9), weight_kg=Decimal("73.0"))
        self.log(self.hadi, date(2026, 11, 9), body_weight_kg=Decimal("73.4"))
        weights = self.get().json()["bodyWeight"]
        self.assertEqual([(w["date"], w["kg"], w["source"]) for w in weights],
                         [("2026-11-02", "74.0", "self"), ("2026-11-09", "73.4", "coach")])

    def test_attendance_over_the_last_90_days(self):
        _pt(self.hadi, self.lea, date(2026, 11, 3), attendance="Attended")
        _pt(self.hadi, self.lea, date(2026, 11, 4), attendance="No-show")
        _pt(self.hadi, self.lea, date(2026, 11, 5), status=PTSession.Status.CANCELLED)
        _pt(self.hadi, self.lea, date(2026, 7, 1), attendance="Attended")          # too long ago
        _pt(self.hadi, self.lea, date(2026, 11, 20))                                # not yet
        spin = _class("Spinning", self.rita, date(2026, 11, 6))
        _book(self.lea, spin)
        ClassBooking.objects.filter(gym_class=spin).update(attendance="Attended")
        att = self.get().json()["attendance"]
        self.assertEqual(att["privateSessions"], {"booked": 2, "attended": 1, "noShows": 1})
        self.assertEqual(att["classes"], {"booked": 1, "attended": 1, "noShows": 0})

    def test_every_coach_of_the_client_sees_all_logs_with_assessments(self):
        mine = self.log(self.hadi, date(2026, 11, 14), plan="Mine", assessment="Strong week")
        self.log(self.rita, date(2026, 11, 13), plan="Rita's", assessment="Tired")
        body = self.get().json()
        self.assertEqual([(l["coachName"], l["assessment"], l["canEdit"]) for l in body["logs"]],
                         [("Hadi", "Strong week", True), ("Rita", "Tired", False)])
        self.assertEqual(body["logCount"], 2)
        self.assertTrue(mine.pk)

    def test_only_the_clients_coaches(self):
        staff_login(self.client, "omar", PASSWORD)
        self.assertEqual(self.get().status_code, 403)
        _pt(self.omar, self.lea, date(2026, 11, 20), status=PTSession.Status.CANCELLED)
        self.assertEqual(self.get().status_code, 403)                # a cancelled booking doesn't count
        _pt(self.omar, self.lea, date(2026, 11, 21))
        self.assertEqual(self.get().status_code, 200)
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.get().status_code, 403)

    def test_the_member_sees_their_progress_without_the_coaches_assessments(self):
        self.log(self.hadi, date(2026, 11, 14), [{"exercise": "Squat", "sets": 3, "reps": 5, "weight_kg": Decimal("80")}],
                 subjective="Good", plan="More squats", assessment="Private judgement")
        self.client.logout()
        self.assertEqual(self.client.get("/api/members/me/progress").status_code, 401)
        _member_login(self.client, "lea")
        body = self.client.get("/api/members/me/progress").json()
        [log] = body["logs"]
        self.assertEqual((log["subjective"], log["plan"]), ("Good", "More squats"))
        self.assertNotIn("assessment", log)
        self.assertNotIn("canEdit", log)
        self.assertNotIn("Private judgement", str(body))
        self.assertEqual(body["strength"][0]["latest"], "93.3")


class GoalTests(FrozenClock):
    @classmethod
    def setUpTestData(cls):
        cls.hadi = _coach("hadi")
        cls.omar = _coach("omar")
        cls.lea = _member("Lea Haddad", "lea", days_valid=400)

    def setUp(self):
        super().setUp()
        _pt(self.hadi, self.lea, date(2026, 11, 20))   # Hadi coaches Lea
        staff_login(self.client, "hadi", PASSWORD)

    def add(self, **body):
        body = {"kind": "strength", "exercise": "Squat", "targetValue": "100", "targetDate": "2027-03-01", **body}
        return self.client.post(f"/api/coaching/clients/{self.lea.id}/goals", body, content_type="application/json")

    def patch(self, goal_id, body):
        return self.client.patch(f"/api/coaching/goals/{goal_id}", body, content_type="application/json")

    def squat(self, day, weight, reps=5, start="08:00"):
        session = _pt(self.hadi, self.lea, day, start=start)
        log = SessionLog.objects.create(session=session, member=self.lea, coach=self.hadi)
        log.exercises.create(kind="strength", exercise="Squat", sets=3, reps=reps, weight_kg=Decimal(weight))

    def test_a_strength_goal_tracks_the_best_lift_since_it_was_set(self):
        self.squat(date(2026, 11, 10), "80")                # e1RM 93.3 - the starting point
        res = self.add()
        self.assertEqual(res.status_code, 201, res.content)
        goal = res.json()
        self.assertEqual((goal["title"], goal["start"], goal["current"], goal["percent"], goal["reached"]),
                         ("Squat 100 kg (estimated 1-rep max)", "93.3", None, None, None))
        self.squat(TODAY, "85")                              # 99.2: 88% of the way
        goal = self.client.get(f"/api/coaching/clients/{self.lea.id}/progress").json()["goals"][0]
        self.assertEqual((goal["current"], goal["percent"], goal["reached"], goal["daysLeft"]), ("99.2", 88, False, 106))
        self.squat(TODAY, "90", reps=3, start="09:00")       # 99.0 - a lighter set doesn't lower progress
        self.squat(TODAY, "95", reps=2, start="10:00")       # 101.3
        goal = self.client.get(f"/api/coaching/clients/{self.lea.id}/progress").json()["goals"][0]
        self.assertEqual((goal["current"], goal["percent"], goal["reached"]), ("101.3", 100, True))

    def test_a_weight_loss_goal(self):
        BodyMetric.objects.create(member=self.lea, measured_on=date(2026, 11, 1), weight_kg=Decimal("80.0"))
        res = self.add(kind="body_weight", targetValue="75", exercise="Ignored")
        goal = res.json()
        self.assertEqual((goal["title"], goal["start"], goal["exercise"]), ("Reach 75 kg body weight", "80.0", ""))
        BodyMetric.objects.create(member=self.lea, measured_on=date(2026, 11, 14), weight_kg=Decimal("78.0"))
        goal = self.client.get(f"/api/coaching/clients/{self.lea.id}/progress").json()["goals"][0]
        self.assertEqual((goal["current"], goal["percent"], goal["reached"]), ("78.0", 40, False))

    def test_a_goal_set_before_any_data_starts_from_the_first_measurement(self):
        self.add(kind="body_weight", targetValue="70")
        BodyMetric.objects.create(member=self.lea, measured_on=TODAY, weight_kg=Decimal("76.0"))
        goal = self.client.get(f"/api/coaching/clients/{self.lea.id}/progress").json()["goals"][0]
        self.assertEqual((goal["start"], goal["current"], goal["percent"]), ("76.0", "76.0", 0))

    def test_a_custom_goal_is_marked_by_the_coach(self):
        self.assertIn("title", self.add(kind="custom", targetValue=None).json()["error"])
        goal = self.add(kind="custom", title="Run 5 km without stopping", targetValue="5").json()
        self.assertEqual((goal["percent"], goal["target"], goal["unit"]), (None, None, ""))
        res = self.patch(goal["id"], {"status": "Achieved"})
        self.assertEqual((res.json()["status"], res.json()["closedOn"]), ("Achieved", "2026-11-15"))
        res = self.patch(goal["id"], {"status": "Active"})
        self.assertEqual((res.json()["status"], res.json()["closedOn"]), ("Active", None))

    def test_what_a_goal_must_be(self):
        self.squat(date(2026, 11, 10), "80")
        for body, field in [({"targetDate": "2026-11-15"}, "targetDate"), ({"targetDate": "2029-01-01"}, "targetDate"),
                            ({"exercise": ""}, "exercise"), ({"targetValue": "0"}, "targetValue"),
                            ({"targetValue": None}, "targetValue"), ({"kind": "body_weight", "targetValue": "400"}, "targetValue"),
                            ({"kind": "fly"}, "kind"), ({"targetValue": "90"}, "targetValue")]:   # 90 < 93.3 already
            res = self.add(**body)
            self.assertEqual(res.status_code, 400, body)
            self.assertIn(field, res.json()["error"], body)
        self.assertFalse(ClientGoal.objects.exists())

    def test_at_most_ten_active_goals(self):
        for i in range(10):
            self.add(kind="custom", title=f"Goal {i}")
        self.assertEqual(self.add().status_code, 409)
        first = ClientGoal.objects.first()
        self.patch(first.id, {"status": "Dropped"})
        self.assertEqual(self.add().status_code, 201)
        self.assertEqual(self.patch(first.id, {"status": "Active"}).status_code, 409)

    def test_editing_a_goal(self):
        goal = self.add().json()
        res = self.patch(goal["id"], {"targetValue": "110", "targetDate": "2027-06-01", "note": "Competition in June"})
        self.assertEqual((res.json()["target"], res.json()["targetDate"], res.json()["note"]), ("110.0", "2027-06-01", "Competition in June"))
        self.assertEqual(self.patch(goal["id"], {"kind": "custom"}).status_code, 400)
        staff_login(self.client, "omar", PASSWORD)                    # not Lea's coach
        self.assertEqual(self.patch(goal["id"], {"status": "Dropped"}).status_code, 404)
        self.assertEqual(self.add().status_code, 403)

    def test_an_overdue_goal(self):
        goal = ClientGoal.objects.create(member=self.lea, kind="custom", title="Plank 2 min", target_date=date(2026, 11, 1))
        [payload] = self.client.get(f"/api/coaching/clients/{self.lea.id}/progress").json()["goals"]
        self.assertTrue(payload["overdue"])
        self.assertEqual(payload["daysLeft"], -14)
        self.assertTrue(goal.pk)

    def test_logs_and_goals_are_exported_and_erased_with_the_member(self):
        self.squat(date(2026, 11, 10), "80")
        SessionLog.objects.update(plan="Keep going")
        self.add()
        _member_login(self.client, "lea")
        export = self.client.get("/api/members/me/export").content
        self.assertIn(b"Keep going", export)
        self.assertIn(b"Squat 100 kg", export)
        res = self.client.post("/api/members/me/delete", {"password": PASSWORD, "confirm": "DELETE"},
                               content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(SessionLog.objects.exists())
        self.assertFalse(ClientGoal.objects.exists())
