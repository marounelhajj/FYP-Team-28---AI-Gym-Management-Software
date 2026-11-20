import uuid
from datetime import date, datetime, time, timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from notifications.models import MemberNotification, StaffNotification

from .models import CoverRequest, GymClass, PTSession, TimeOff
from .rules import local_datetime
from .tests import PASSWORD, _book, _class, _coach, _member, _member_login, _staff

# Every test runs at noon on Sunday 15 November 2026, Beirut time.
NOW = timezone.make_aware(datetime(2026, 11, 15, 12, 0))
TODAY = date(2026, 11, 15)
TOMORROW = date(2026, 11, 16)


def _at(day, clock):
    return local_datetime(day, time.fromisoformat(clock))


class FrozenClock(TestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=NOW)
        self.clock = patcher.start()
        self.addCleanup(patcher.stop)


class CoverBase(FrozenClock):
    @classmethod
    def setUpTestData(cls):
        cls.bm = _staff("bm", ["manage_class_schedule", "manage_members"], branch="Hamra")
        _staff("jnah_bm", ["manage_class_schedule"], branch="Jnah")
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        cls.hadi = _coach("hadi")
        cls.rita = _coach("rita")
        cls.omar = _coach("omar")
        cls.lara = _coach("lara", branch="Jnah")
        cls.joe = _staff("joe", [], branch=None, job_title=StaffAccount.JobTitle.COACH)   # works at every branch
        cls.gone = _coach("gone", active=False)
        cls.lea = _member("Lea Haddad", "lea")

    def setUp(self):
        super().setUp()
        self.spin = _class("Spinning", self.hadi, TOMORROW, start="18:00", room="Cycle Studio")
        _book(self.lea, self.spin)

    def staff_notes(self, username):
        return list(StaffNotification.objects.filter(recipient__username=username).values_list("title", flat=True))


# The coach: "I can't make it".
class CoachReportsTests(CoverBase):
    def setUp(self):
        super().setUp()
        staff_login(self.client, "hadi", PASSWORD)

    def report(self, gym_class=None, reason="Sick - fever since last night"):
        return self.client.post(f"/api/classes/me/classes/{(gym_class or self.spin).id}/cover", {"reason": reason},
                                content_type="application/json")

    def test_reporting_alerts_the_branchs_managers_and_flags_the_class(self):
        res = self.report()
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["status"], res.json()["originalCoach"], res.json()["managersNotified"]), ("Open", "Hadi", 1))
        self.assertEqual(self.staff_notes("bm"), ["Cover needed - Spinning tomorrow at 18:00"])
        self.assertEqual(self.staff_notes("jnah_bm") + self.staff_notes("desk"), [])
        entry = AuditLog.objects.get(action=AuditLog.Action.CLASS_COVER_REQUESTED)
        self.assertEqual(entry.details, {"reason": "Sick - fever since last night"})
        # The coach stays on the class until someone takes over.
        self.spin.refresh_from_db()
        self.assertEqual(self.spin.coach, self.hadi)
        mine = self.client.get("/api/classes/me/schedule", {"week": str(TOMORROW)}).json()["classes"]
        self.assertEqual([(c["id"], c["needsCover"]) for c in mine], [(self.spin.id, True)])

    def test_close_to_the_start_it_is_urgent(self):
        soon = _class("Yoga", self.hadi, TODAY, start="14:00")
        self.report(soon)
        self.assertEqual(self.staff_notes("bm"), ["Urgent: Cover needed - Yoga today at 14:00"])

    def test_even_once_started_a_coach_can_ask(self):
        running = _class("Yoga", self.hadi, TODAY, start="11:30")
        self.assertEqual(self.report(running, "Stuck in traffic").status_code, 201)

    def test_when_a_coach_cant_ask(self):
        self.assertEqual(self.report().status_code, 201)
        self.assertEqual(self.report().status_code, 409)                                   # already asked
        ritas = _class("Pilates", self.rita, TOMORROW, start="08:00")
        self.assertEqual(self.report(ritas).status_code, 403)                              # not theirs
        over = _class("Yoga", self.hadi, TODAY, start="09:00")
        self.assertEqual(self.report(over).status_code, 409)                               # already happened
        cancelled = _class("Yoga", self.hadi, TOMORROW, start="08:00")
        GymClass.objects.filter(pk=cancelled.pk).update(status=GymClass.Status.CANCELLED)
        self.assertEqual(self.report(cancelled).status_code, 409)
        res = self.report(_class("Yoga", self.hadi, TOMORROW, start="10:00"), reason="  ")
        self.assertIn("reason", res.json()["error"])
        self.assertEqual(self.client.post("/api/classes/me/classes/999999/cover", {"reason": "x"},
                                          content_type="application/json").status_code, 404)
        self.client.logout()
        self.assertEqual(self.report().status_code, 401)

    def test_withdrawing_when_the_coach_can_make_it_after_all(self):
        url = f"/api/classes/me/classes/{self.spin.id}/cover"
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.report()
        res = self.client.delete(url)
        self.assertEqual(res.json()["status"], "Withdrawn")
        self.assertIn("No cover needed: Spinning tomorrow at 18:00", self.staff_notes("bm"))
        staff_login(self.client, "bm", PASSWORD)
        week = self.client.get("/api/classes", {"week": str(TOMORROW)}).json()["classes"]
        self.assertFalse(next(c for c in week if c["id"] == self.spin.id)["needsCover"])


# The branch manager: finding and assigning a substitute.
class SubstituteTests(CoverBase):
    def setUp(self):
        super().setUp()
        staff_login(self.client, "bm", PASSWORD)

    def candidates(self, gym_class=None):
        return self.client.get(f"/api/classes/{(gym_class or self.spin).id}/substitutes")

    def assign(self, coach, gym_class=None, reason="Called in sick"):
        body = {"coachId": coach.id if coach else 999999, **({"reason": reason} if reason is not None else {})}
        return self.client.post(f"/api/classes/{(gym_class or self.spin).id}/substitute", body, content_type="application/json")

    def test_free_coaches_first_then_those_who_know_the_class(self):
        for weeks in (1, 2, 3):                                    # Omar has taught Spinning three times
            _class("Spinning", self.omar, TODAY - timedelta(weeks=weeks), start="07:00")
        _class("Spinning", self.joe, TODAY - timedelta(weeks=1), start="09:00")
        _class("Boxing", self.rita, TOMORROW, start="17:30", branch="Jnah")       # Rita is busy at Jnah then
        starts = _at(TOMORROW, "18:30")
        TimeOff.objects.create(coach=self.joe, starts_at=starts - timedelta(hours=2), ends_at=starts + timedelta(hours=2), reason="Dentist")
        body = self.candidates().json()
        self.assertEqual((body["currentCoach"]["name"], body["started"], body["coverRequest"]), ("Hadi", False, None))
        people = [(c["name"], c["available"], c["taughtThisType"]) for c in body["candidates"]]
        # Hadi (teaching it), Lara (Jnah only) and the deactivated coach aren't offered.
        self.assertEqual(people, [("Omar", True, 3), ("Joe", False, 1), ("Rita", False, 0)])
        busy = {c["name"]: c["busyReason"] for c in body["candidates"]}
        self.assertIn("marked that time unavailable: Dentist", busy["Joe"])
        self.assertIn("already teaches Boxing", busy["Rita"])
        self.assertIn("at Jnah", busy["Rita"])

    def test_a_private_session_makes_a_coach_busy(self):
        starts = _at(TOMORROW, "18:00")
        PTSession.objects.create(coach=self.rita, member=self.lea, branch="Hamra", starts_at=starts, ends_at=starts + timedelta(hours=1))
        rita = next(c for c in self.candidates().json()["candidates"] if c["name"] == "Rita")
        self.assertEqual((rita["available"], rita["busyReason"][:23]), (False, "Rita has a private trai"))

    def test_covering_a_coachs_request(self):
        CoverRequest.objects.create(gym_class=self.spin, original_coach=self.hadi, reason="Fever", reported_by=self.hadi)
        self.assertEqual(self.candidates().json()["coverRequest"]["reason"], "Fever")
        res = self.assign(self.rita, reason=None)                         # the coach's reason is used
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["status"], res.json()["substitute"], res.json()["reason"], res.json()["membersNotified"]),
                         ("Covered", "Rita", "Fever", True))
        self.spin.refresh_from_db()
        self.assertEqual(self.spin.coach, self.rita)
        self.assertEqual(self.staff_notes("rita"), ["You're covering Spinning tomorrow at 18:00"])
        self.assertEqual(self.staff_notes("hadi"), ["Rita is covering your Spinning tomorrow at 18:00"])
        note = MemberNotification.objects.get(recipient=self.lea)
        self.assertEqual(note.kind, MemberNotification.Kind.CLASS_CHANGED)
        self.assertIn("Rita is coaching it instead of Hadi", note.message)
        entry = AuditLog.objects.get(action=AuditLog.Action.CLASS_COVER_ASSIGNED)
        self.assertEqual(entry.details, {"from": "Hadi", "to": "Rita", "reason": "Fever", "afterStart": False})
        # The calendar shows who's covering for whom; the class moved schedules.
        week = self.client.get("/api/classes", {"week": str(TOMORROW)}).json()["classes"]
        card = next(c for c in week if c["id"] == self.spin.id)
        self.assertEqual((card["coachName"], card["coverFor"], card["needsCover"]), ("Rita", "Hadi", False))
        staff_login(self.client, "rita", PASSWORD)
        ritas = self.client.get("/api/classes/me/schedule", {"week": str(TOMORROW)}).json()["classes"]
        self.assertEqual([(c["id"], c["coverFor"]) for c in ritas], [(self.spin.id, "Hadi")])
        staff_login(self.client, "hadi", PASSWORD)
        self.assertEqual(self.client.get("/api/classes/me/schedule", {"week": str(TOMORROW)}).json()["classes"], [])

    def test_a_manager_who_hears_first_reassigns_straight_away_with_a_reason(self):
        res = self.assign(self.rita, reason="")
        self.assertEqual(res.status_code, 400)
        self.assertIn("reason", res.json()["error"])
        res = self.assign(self.joe, reason="Hadi phoned in sick")
        self.assertEqual(res.status_code, 200, res.content)
        cover = CoverRequest.objects.get()
        self.assertEqual((cover.status, cover.original_coach, cover.substitute, cover.reported_by), ("Covered", self.hadi, self.joe, self.bm))

    def test_who_cant_be_the_substitute(self):
        _class("Boxing", self.rita, TOMORROW, start="18:30")
        res = self.assign(self.rita)
        self.assertEqual(res.status_code, 409)
        self.assertIn("already teaches Boxing", res.json()["error"]["coachId"][0])
        for coach, message in [(self.hadi, "already teaching this class"), (self.lara, "coaches at Jnah"),
                               (self.gone, "deactivated"), (None, "Choose a coach"),
                               (StaffAccount.objects.get(username="desk"), "isn't a coach")]:
            res = self.assign(coach)
            self.assertEqual(res.status_code, 400, coach)
            self.assertIn(message, res.json()["error"]["coachId"][0])
        self.spin.refresh_from_db()
        self.assertEqual(self.spin.coach, self.hadi)

    def test_not_for_a_class_that_ended_or_was_cancelled(self):
        over = _class("Yoga", self.hadi, TODAY, start="09:00")
        self.assertEqual(self.assign(self.rita, over).status_code, 409)
        GymClass.objects.filter(pk=self.spin.pk).update(status=GymClass.Status.CANCELLED)
        self.assertEqual(self.assign(self.rita).status_code, 409)

    def test_a_no_show_coach_can_be_replaced_after_the_start(self):
        running = _class("Yoga", self.hadi, TODAY, start="11:45")
        _book(self.lea, running)
        res = self.assign(self.omar, running, reason="Didn't turn up")
        self.assertEqual((res.status_code, res.json()["membersNotified"]), (200, False))
        self.assertFalse(MemberNotification.objects.exists())        # they're already in the room
        self.assertTrue(AuditLog.objects.get(action=AuditLog.Action.CLASS_COVER_ASSIGNED).details["afterStart"])
        # Attendance (and the health briefing) are now the substitute's to take.
        staff_login(self.client, "omar", PASSWORD)
        self.assertEqual(self.client.get(f"/api/classes/{running.id}/attendance").status_code, 200)
        self.assertEqual(self.client.get(f"/api/health-notes/classes/{running.id}").status_code, 200)
        staff_login(self.client, "hadi", PASSWORD)
        self.assertEqual(self.client.get(f"/api/classes/{running.id}/attendance").status_code, 403)

    def test_only_this_branchs_managers(self):
        for username, expected in (("desk", 403), ("jnah_bm", 403), ("hadi", 403)):
            staff_login(self.client, username, PASSWORD)
            self.assertEqual(self.candidates().status_code, expected, username)
            self.assertEqual(self.assign(self.rita).status_code, expected, username)
        self.client.logout()
        self.assertEqual(self.candidates().status_code, 401)
        _member_login(self.client, "lea")
        self.assertEqual(self.assign(self.rita).status_code, 401)

    def test_the_queue_of_classes_needing_cover(self):
        later = _class("Yoga", self.hadi, TOMORROW, start="20:00")
        soon = _class("Pilates", self.hadi, TODAY, start="13:00")
        ended = _class("Boxing", self.hadi, TODAY, start="08:00")
        for c in (later, soon, ended):
            CoverRequest.objects.create(gym_class=c, original_coach=self.hadi, reason="Sick", reported_by=self.hadi)
        body = self.client.get("/api/classes/cover-requests").json()
        self.assertEqual([(r["className"], r["urgent"]) for r in body["results"]], [("Pilates", True), ("Yoga", False)])
        self.assertEqual(CoverRequest.objects.get(gym_class=ended).status, "Closed")   # ended without cover
        self.assertEqual(self.client.get("/api/classes/cover-requests", {"branch": "Jnah"}).status_code, 403)

    def test_cancelling_the_class_closes_its_request(self):
        CoverRequest.objects.create(gym_class=self.spin, original_coach=self.hadi, reason="Sick", reported_by=self.hadi)
        res = self.client.post(f"/api/classes/{self.spin.id}/cancel", {"reason": "No cover found"}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(CoverRequest.objects.get().status, "Closed")
        self.assertEqual(self.client.get("/api/classes/cover-requests").json()["results"], [])

    def test_only_this_session_changes_not_the_series(self):
        series = GymClass.objects.filter(pk=self.spin.pk)
        next_week = _class("Spinning", self.hadi, TOMORROW + timedelta(weeks=1), start="18:00")
        sid = uuid.uuid4()
        series.update(series=sid)
        GymClass.objects.filter(pk=next_week.pk).update(series=sid)
        self.assign(self.rita)
        next_week.refresh_from_db()
        self.assertEqual(next_week.coach, self.hadi)
