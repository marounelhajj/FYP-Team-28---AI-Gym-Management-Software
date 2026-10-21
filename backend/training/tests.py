from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.test import TestCase

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from checkins.models import CheckIn
from members import qr
from members.models import Member

from .events import delete_training_events_for_member, log_training_event
from .models import TrainingEvent, TrainingEventImmutable

PASSWORD = "ChangeMe123!"
EventType = TrainingEvent.EventType


def _staff(username, role, branch=None):
    account = StaffAccount(
        full_name=username.title(), email=f"{username}@gym.com", username=username,
        job_title=StaffAccount.JobTitle.RECEPTIONIST, role=role, branch=branch,
    )
    account.set_password(PASSWORD)
    account.save()
    return account


def _member(name, username=None, branch="Hamra"):
    member = Member(
        name=name, email=f"{name.split()[0].lower()}@example.com", phone="1", branch=branch,
        join_date=date.today(), username=username, subscription_expires_at=date.today() + timedelta(days=30),
    )
    if username:
        member.set_password(PASSWORD)
    member.save()
    return member


# User story (SCRUM-73): "As a system administrator, I want check-ins,
# cancellations, no-shows, and trainer accept/reject decisions logged as
# training data from first release, so that the models have a dataset to
# learn from later."
class CaptureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        desk_role = Role.objects.create(name="Receptionist", permissions=["manage_members"])
        _staff("desk", desk_role)
        _staff("jnahdesk", desk_role, branch="Jnah")
        cls.lea = _member("Lea Haddad", username="lea")

    def post(self, path, body=None):
        return self.client.post(path, body or {}, content_type="application/json")

    # AC: events are captured with timestamp, member id and branch id.
    def test_check_in_is_logged_with_timestamp_member_and_branch(self):
        staff_login(self.client, "desk", PASSWORD)
        res = self.post("/api/checkins", {"membershipId": self.lea.id})
        self.assertEqual(res.status_code, 201, res.content)

        event = TrainingEvent.objects.get()
        check_in = CheckIn.objects.get()
        self.assertEqual(event.event_type, EventType.CHECK_IN)
        self.assertEqual(event.member_id, self.lea.id)
        self.assertEqual(event.branch, "Hamra")
        self.assertEqual(event.occurred_at, check_in.checked_in_at)
        self.assertEqual(event.occurred_at.utcoffset(), timedelta(0))
        self.assertEqual(event.payload, {"checkInId": check_in.id, "method": "membership_id"})

    def test_check_in_records_the_desk_branch_and_qr_method(self):
        staff_login(self.client, "jnahdesk", PASSWORD)
        self.post("/api/checkins", {"qrCode": qr.payload_for(self.lea)})
        event = TrainingEvent.objects.get()
        self.assertEqual(event.branch, "Jnah")
        self.assertEqual(event.payload["method"], "qr")

    def test_refused_check_ins_are_not_training_events(self):
        staff_login(self.client, "desk", PASSWORD)
        self.post("/api/checkins", {"membershipId": self.lea.id})
        res = self.post("/api/checkins", {"membershipId": self.lea.id})
        self.assertEqual(res.json()["checkIn"]["reason"], "Already checked in")
        self.assertEqual(TrainingEvent.objects.count(), 1)

    def test_front_desk_cancellation_is_logged(self):
        staff_login(self.client, "desk", PASSWORD)
        res = self.post(f"/api/members/{self.lea.id}/cancel")
        self.assertEqual(res.status_code, 200, res.content)
        event = TrainingEvent.objects.get()
        self.assertEqual(event.event_type, EventType.CANCELLATION)
        self.assertEqual((event.member_id, event.branch), (self.lea.id, "Hamra"))
        self.assertEqual(event.payload, {"previousStatus": "Active", "channel": "front_desk"})

    def test_self_service_cancellation_is_logged(self):
        self.post("/api/members/login", {"username": "lea", "password": PASSWORD})
        res = self.post("/api/members/me/cancel")
        self.assertEqual(res.status_code, 200, res.content)
        event = TrainingEvent.objects.get()
        self.assertEqual(event.event_type, EventType.CANCELLATION)
        self.assertEqual(event.payload["channel"], "app")

    # AC: logging is active from the first production release - there's no
    # switch to turn on; the normal code paths always write events.
    def test_logging_needs_no_configuration(self):
        staff_login(self.client, "desk", PASSWORD)
        self.post("/api/checkins", {"membershipId": self.lea.id})
        self.post(f"/api/members/{self.lea.id}/cancel")
        self.assertEqual(
            sorted(TrainingEvent.objects.values_list("event_type", flat=True)), ["cancellation", "check_in"],
        )

    # Logging must never break the action it describes.
    def test_a_failed_write_does_not_break_check_in(self):
        staff_login(self.client, "desk", PASSWORD)
        with mock.patch.object(TrainingEvent.objects, "create", side_effect=RuntimeError("disk full")), \
                self.assertLogs("training.events", level="ERROR"):
            res = self.post("/api/checkins", {"membershipId": self.lea.id})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["checkIn"]["result"], "Allowed")
        self.assertEqual(CheckIn.objects.count(), 1)
        self.assertEqual(TrainingEvent.objects.count(), 0)

    def test_a_failed_write_does_not_break_cancellation(self):
        staff_login(self.client, "desk", PASSWORD)
        with mock.patch.object(TrainingEvent.objects, "create", side_effect=RuntimeError("disk full")), \
                self.assertLogs("training.events", level="ERROR"):
            res = self.post(f"/api/members/{self.lea.id}/cancel")
        self.assertEqual(res.status_code, 200)
        self.lea.refresh_from_db()
        self.assertEqual(self.lea.status, Member.Status.CANCELLED)


class StoreTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lea = _member("Lea Haddad")
        cls.sami = _member("Sami Khoury", branch="Jnah")

    def test_logs_the_event_types_not_wired_yet(self):
        coach_role = Role.objects.create(name="Coach", permissions=[])
        coach = _staff("coach", coach_role, branch="Hamra")
        for event_type in (EventType.NO_SHOW, EventType.TRAINER_ACCEPT, EventType.TRAINER_REJECT):
            event = log_training_event(event_type, member=self.lea, trainer=coach, session_id=42)
            self.assertEqual((event.event_type, event.trainer_id, event.session_id), (event_type, coach.id, "42"))

    # Append-only: rows can't be edited after they're written.
    def test_events_cannot_be_edited(self):
        event = log_training_event(EventType.CHECK_IN, member=self.lea)
        event.branch = "Zalka"
        with self.assertRaises(TrainingEventImmutable):
            event.save()
        with self.assertRaises(TrainingEventImmutable):
            TrainingEvent.objects.update(branch="Zalka")

    # AC: retention respects the member data deletion request flow.
    def test_delete_training_events_for_member(self):
        log_training_event(EventType.CHECK_IN, member=self.lea)
        log_training_event(EventType.CANCELLATION, member=self.lea)
        log_training_event(EventType.CHECK_IN, member=self.sami)

        self.assertEqual(delete_training_events_for_member(self.lea.id), 2)
        self.assertFalse(TrainingEvent.objects.filter(member_id=self.lea.id).exists())
        self.assertEqual(TrainingEvent.objects.filter(member_id=self.sami.id).count(), 1)
        self.assertEqual(delete_training_events_for_member(self.lea.id), 0)

    def test_deleting_a_member_deletes_their_events(self):
        log_training_event(EventType.CHECK_IN, member=self.sami)
        self.sami.delete()
        self.assertEqual(TrainingEvent.objects.count(), 0)


# AC: data is retained in a queryable store - GET /api/training-events.
class QueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        admin_role = Role.objects.create(name="System Administrator", permissions=["view_training_data"])
        desk_role = Role.objects.create(name="Receptionist", permissions=["manage_members"])
        _staff("admin", admin_role)
        _staff("desk", desk_role)
        cls.lea = _member("Lea Haddad")
        cls.sami = _member("Sami Khoury", branch="Jnah")

        def at(day, hour):
            return datetime(2026, 10, day, hour, tzinfo=dt_timezone.utc)

        log_training_event(EventType.CHECK_IN, member=cls.lea, occurred_at=at(1, 9))
        log_training_event(EventType.CHECK_IN, member=cls.sami, occurred_at=at(5, 18))
        log_training_event(EventType.CANCELLATION, member=cls.lea, occurred_at=at(10, 12))

    def get(self, query=""):
        return self.client.get(f"/api/training-events{query}")

    def test_requires_view_training_data(self):
        self.assertEqual(self.get().status_code, 401)
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.get().status_code, 403)

    def test_lists_newest_first(self):
        staff_login(self.client, "admin", PASSWORD)
        body = self.get().json()
        self.assertEqual(body["total"], 3)
        self.assertEqual([r["eventType"] for r in body["results"]], ["cancellation", "check_in", "check_in"])
        first = body["results"][0]
        self.assertEqual(
            set(first), {"id", "eventType", "occurredAt", "memberId", "branch", "trainerId", "sessionId", "payload"},
        )
        self.assertEqual(first["memberId"], self.lea.id)
        self.assertTrue(first["occurredAt"].endswith("Z"))

    def test_filters(self):
        staff_login(self.client, "admin", PASSWORD)
        self.assertEqual(self.get("?eventType=check_in").json()["total"], 2)
        self.assertEqual(self.get("?branch=Jnah").json()["total"], 1)
        self.assertEqual(self.get(f"?memberId={self.lea.id}").json()["total"], 2)
        self.assertEqual(self.get("?dateFrom=2026-10-05&dateTo=2026-10-05").json()["total"], 1)
        self.assertEqual(self.get("?eventType=check_in&dateFrom=2026-10-02").json()["total"], 1)

    def test_bad_filters(self):
        staff_login(self.client, "admin", PASSWORD)
        for query in ("?eventType=visit", "?branch=Paris", "?dateFrom=yesterday", "?memberId=abc",
                      "?dateFrom=2026-10-09&dateTo=2026-10-01"):
            self.assertEqual(self.get(query).status_code, 400, query)
