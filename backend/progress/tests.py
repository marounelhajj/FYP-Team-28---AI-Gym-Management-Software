from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from classes.models import PTSession
from classes.tests import PASSWORD, _coach, _member, _member_login, _staff
from training.models import TrainingEvent

from .models import BodyMetric, WorkoutEntry


def _pt(coach, member, days=-3, status=PTSession.Status.BOOKED):
    start = timezone.now() + timedelta(days=days)
    return PTSession.objects.create(coach=coach, member=member, branch="Hamra", starts_at=start,
                                    ends_at=start + timedelta(hours=1), status=status)


# User story (SCRUM-60): "As a member, I want to log my own workouts and body
# metrics between sessions, so that my coach and the AI system have
# up-to-date data to base recommendations on."
class WorkoutLogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lea = _member("Lea Haddad", "lea")
        cls.sami = _member("Sami Khoury", "sami")
        cls.coach = _coach("hadi")
        cls.other_coach = _coach("rita")
        cls.cancelled_coach = _coach("omar")
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        _pt(cls.coach, cls.lea)
        _pt(cls.cancelled_coach, cls.lea, status=PTSession.Status.CANCELLED)

    def setUp(self):
        _member_login(self.client, "lea")
        self.today = timezone.localdate()

    def post(self, path, body):
        return self.client.post(f"/api/members/me/{path}", body, content_type="application/json")

    def patch(self, path, body):
        return self.client.patch(f"/api/members/me/{path}", body, content_type="application/json")

    def squat(self, **overrides):
        body = {"date": str(self.today), "exercise": "Squat", "sets": 4, "reps": 8, "weightKg": "80"}
        body.update(overrides)
        return self.post("workouts", body)

    # --- workouts CRUD ----------------------------------------------------

    def test_log_a_strength_workout(self):
        res = self.squat(note="felt strong")
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertEqual((body["exercise"], body["kind"], body["sets"], body["reps"], body["weightKg"]), ("Squat", "strength", 4, 8, "80.0"))
        self.assertEqual(WorkoutEntry.objects.get().member, self.lea)

    def test_log_cardio_by_duration_or_distance(self):
        res = self.post("workouts", {"date": str(self.today), "exercise": "Running", "distanceKm": "5.2", "durationMinutes": 31})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["kind"], "cardio")
        self.assertIsNone(res.json()["sets"])

    def test_free_text_exercise(self):
        res = self.post("workouts", {"date": str(self.today), "exercise": "  Kettlebell   swings ", "sets": 3, "reps": 15})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["exercise"], res.json()["kind"]), ("Kettlebell swings", "strength"))
        res = self.post("workouts", {"date": str(self.today), "exercise": "Hiking", "kind": "cardio", "durationMinutes": 90})
        self.assertEqual(res.status_code, 201, res.content)

    def test_list_edit_and_delete_my_workouts(self):
        entry_id = self.squat().json()["id"]
        listing = self.client.get("/api/members/me/workouts").json()
        self.assertEqual([w["id"] for w in listing["results"]], [entry_id])
        self.assertIn({"name": "Bench press", "kind": "strength"}, listing["exercises"])

        res = self.patch(f"workouts/{entry_id}", {"reps": 10, "weightKg": "85"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["reps"], res.json()["weightKg"]), (10, "85.0"))

        self.assertEqual(self.client.delete(f"/api/members/me/workouts/{entry_id}").status_code, 204)
        self.assertFalse(WorkoutEntry.objects.exists())

    def test_cannot_touch_someone_elses_workout(self):
        other = WorkoutEntry.objects.create(member=self.sami, performed_on=self.today, exercise="Squat", kind="strength", sets=1, reps=1)
        self.assertEqual(self.patch(f"workouts/{other.id}", {"reps": 2}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/members/me/workouts/{other.id}").status_code, 404)
        self.assertNotIn(other.id, [w["id"] for w in self.client.get("/api/members/me/workouts").json()["results"]])

    # --- validation -------------------------------------------------------

    def test_workout_validation(self):
        bad = [
            {"date": str(self.today + timedelta(days=1))},
            {"date": str(self.today - timedelta(days=800))},
            {"sets": 0}, {"sets": 50}, {"reps": 0}, {"weightKg": "900"}, {"weightKg": "-5"},
            {"sets": None}, {"exercise": "   "},
        ]
        for overrides in bad:
            self.assertEqual(self.squat(**overrides).status_code, 400, overrides)
        cardio = {"date": str(self.today), "exercise": "Cycling"}
        self.assertEqual(self.post("workouts", cardio).status_code, 400)  # no duration or distance
        self.assertEqual(self.post("workouts", {**cardio, "durationMinutes": 1000}).status_code, 400)
        self.assertEqual(self.post("workouts", {**cardio, "distanceKm": "0"}).status_code, 400)
        self.assertFalse(WorkoutEntry.objects.exists())

    def test_metrics_validation(self):
        good = {"date": str(self.today), "weightKg": "72.4", "bodyFatPercent": "18.5", "waistCm": "81"}
        for overrides in ({"weightKg": "5"}, {"weightKg": "400"}, {"bodyFatPercent": "90"}, {"waistCm": "10"},
                          {"date": str(self.today + timedelta(days=2))}, {"weightKg": None}):
            self.assertEqual(self.post("metrics", {**good, **overrides}).status_code, 400, overrides)
        self.assertEqual(self.post("metrics", good).status_code, 201)
        res = self.post("metrics", {**good, "weightKg": "72.0"})
        self.assertEqual(res.status_code, 400)  # one entry per day
        self.assertIn("date", res.json()["error"])

    # --- metrics CRUD -----------------------------------------------------

    def test_log_edit_and_delete_body_metrics(self):
        res = self.post("metrics", {"date": str(self.today - timedelta(days=7)), "weightKg": "74.0"})
        self.assertEqual(res.status_code, 201, res.content)
        metric_id = res.json()["id"]
        self.post("metrics", {"date": str(self.today), "weightKg": "73.2", "hipsCm": "96"})
        history = self.client.get("/api/members/me/metrics").json()["results"]
        self.assertEqual([m["weightKg"] for m in history], ["73.2", "74.0"])  # newest first

        self.assertEqual(self.patch(f"metrics/{metric_id}", {"weightKg": "74.5"}).json()["weightKg"], "74.5")
        self.assertEqual(self.client.delete(f"/api/members/me/metrics/{metric_id}").status_code, 204)
        self.assertEqual(BodyMetric.objects.count(), 1)

    def test_needs_a_member_session(self):
        self.client.post("/api/members/logout")
        self.assertEqual(self.client.get("/api/members/me/workouts").status_code, 401)
        self.assertEqual(self.post("metrics", {"date": str(self.today), "weightKg": "70"}).status_code, 401)

    # --- training data (SCRUM-73) -----------------------------------------

    def test_new_entries_are_written_to_the_training_log(self):
        entry_id = self.squat(note="private note").json()["id"]
        metric_id = self.post("metrics", {"date": str(self.today), "weightKg": "73.0"}).json()["id"]

        workout = TrainingEvent.objects.get(event_type="workout_logged")
        self.assertEqual((workout.member, workout.session_id), (self.lea, str(entry_id)))
        self.assertEqual(workout.payload["exercise"], "Squat")
        self.assertNotIn("note", workout.payload)
        metrics = TrainingEvent.objects.get(event_type="metrics_logged")
        self.assertEqual((metrics.session_id, metrics.payload["weightKg"]), (str(metric_id), "73.0"))

    # --- the coach's view -------------------------------------------------

    def _coach_view(self, username, member):
        self.client.post("/api/members/logout")
        staff_login(self.client, username, PASSWORD)
        return self.client.get(f"/api/progress/clients/{member.id}")

    def test_assigned_coach_can_view_but_not_edit(self):
        entry_id = self.squat().json()["id"]
        self.post("metrics", {"date": str(self.today), "weightKg": "73.0"})
        res = self._coach_view("hadi", self.lea)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(len(res.json()["workouts"]), 1)
        self.assertEqual(res.json()["metrics"][0]["weightKg"], "73.0")
        self.assertEqual([c["name"] for c in self.client.get("/api/progress/clients").json()["results"]], ["Lea Haddad"])
        # Staff can't use the member's own endpoints to change anything.
        self.assertEqual(self.client.delete(f"/api/members/me/workouts/{entry_id}").status_code, 401)
        self.assertTrue(WorkoutEntry.objects.filter(id=entry_id).exists())

    def test_unrelated_coach_cannot_view(self):
        self.squat()
        self.assertEqual(self._coach_view("rita", self.lea).status_code, 403)

    def test_a_cancelled_session_does_not_assign_a_coach(self):
        self.assertEqual(self._coach_view("omar", self.lea).status_code, 403)

    def test_other_staff_cannot_view(self):
        self.assertEqual(self._coach_view("desk", self.lea).status_code, 403)

    def test_another_member_cannot_view(self):
        self.client.post("/api/members/logout")
        _member_login(self.client, "sami")
        self.assertEqual(self.client.get(f"/api/progress/clients/{self.lea.id}").status_code, 401)

    # --- export and deletion (SCRUM-62) -----------------------------------

    def test_export_includes_workouts_and_metrics(self):
        self.squat(note="felt strong")
        self.post("metrics", {"date": str(self.today), "weightKg": "73.0", "waistCm": "80"})
        data = self.client.get("/api/members/me/export").json()
        self.assertEqual(data["workouts"][0]["exercise"], "Squat")
        self.assertEqual(data["workouts"][0]["note"], "felt strong")
        self.assertEqual(data["bodyMetrics"][0]["waistCm"], "80.0")

    def test_deletion_erases_workouts_and_metrics(self):
        self.squat()
        self.post("metrics", {"date": str(self.today), "weightKg": "73.0"})
        WorkoutEntry.objects.create(member=self.sami, performed_on=self.today, exercise="Squat", kind="strength", sets=1, reps=1)
        res = self.post("delete", {"password": PASSWORD, "confirm": "DELETE"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertFalse(WorkoutEntry.objects.filter(member=self.lea).exists())
        self.assertFalse(BodyMetric.objects.filter(member=self.lea).exists())
        self.assertTrue(WorkoutEntry.objects.filter(member=self.sami).exists())
        self.assertFalse(TrainingEvent.objects.filter(member=self.lea, event_type="workout_logged").exists())
