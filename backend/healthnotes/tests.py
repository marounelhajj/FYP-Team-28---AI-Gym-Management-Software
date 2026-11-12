from datetime import time, timedelta

from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from classes.models import ClassBooking, GymClass, PTSession
from classes.rules import local_datetime
from classes.tests import PASSWORD, _book, _class, _coach, _day, _member, _member_login, _staff

from .models import HealthDeclaration, HealthNote

KNEE = {"kind": "Injury", "bodyArea": "Knee", "severity": "Severe", "title": "Torn ACL, left knee",
        "details": "No jumping or deep squats.", "since": str(_day(-30))}


def _note(member, title="Lower back pain", severity="Moderate", status="Active", **extra):
    HealthDeclaration.objects.update_or_create(member=member, defaults={"reviewed_at": timezone.now()})
    return HealthNote.objects.create(
        member=member, kind="Injury", body_area="Back", severity=severity, title=title, status=status, **extra,
    )


def _pt(coach, member, day_offset, start="10:00", status=PTSession.Status.BOOKED):
    starts = local_datetime(_day(day_offset), time.fromisoformat(start))
    return PTSession.objects.create(coach=coach, member=member, branch="Hamra", starts_at=starts,
                                    ends_at=starts + timedelta(hours=1), status=status)


# The member's side: keeping their own health notes.
class MyHealthNotesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lea = _member("Lea Haddad", "lea")
        cls.sami = _member("Sami Khoury", "sami")

    def setUp(self):
        _member_login(self.client, "lea")

    def add(self, **changes):
        return self.client.post("/api/members/me/health", {**KNEE, **changes}, content_type="application/json")

    def patch(self, note_id, changes):
        return self.client.patch(f"/api/members/me/health/{note_id}", changes, content_type="application/json")

    def test_starts_empty_and_never_reviewed(self):
        body = self.client.get("/api/members/me/health").json()
        self.assertEqual((body["active"], body["recovered"], body["reviewedOn"]), ([], [], None))
        self.assertEqual([c["value"] for c in body["choices"]["severity"]], ["Mild", "Moderate", "Severe"])
        self.assertIn("front desk and managers can't", body["sharedWith"])

    def test_adding_a_note_also_counts_as_reviewing(self):
        res = self.add()
        self.assertEqual(res.status_code, 201, res.content)
        [note] = res.json()["active"]
        self.assertEqual((note["title"], note["bodyArea"], note["severity"], note["status"]),
                         ("Torn ACL, left knee", "Knee", "Severe", "Active"))
        self.assertEqual(res.json()["reviewedOn"], str(timezone.localdate()))

    def test_what_a_note_needs(self):
        for changes, field in [({"title": "  "}, "title"), ({"title": "ab"}, "title"), ({"severity": "Awful"}, "severity"),
                               ({"kind": ""}, "kind"), ({"bodyArea": "Tail"}, "bodyArea"),
                               ({"since": str(_day(1))}, "since"), ({"since": "1900-01-01"}, "since"),
                               ({"details": "x" * 501}, "details"), ({"title": "x" * 81}, "title")]:
            res = self.add(**changes)
            self.assertEqual(res.status_code, 400, changes)
            self.assertIn(field, res.json()["error"], changes)
        self.assertFalse(HealthNote.objects.exists())
        self.assertFalse(HealthDeclaration.objects.exists())

    def test_only_the_basics_are_required(self):
        res = self.client.post("/api/members/me/health", {"kind": "Medical condition", "severity": "Mild",
                                                          "title": "Asthma"}, content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        note = HealthNote.objects.get()
        self.assertEqual((note.body_area, note.details, note.since), ("General", "", None))

    def test_the_same_active_note_twice_is_refused(self):
        self.add()
        res = self.add(title="torn acl, LEFT knee")
        self.assertEqual(res.status_code, 400)
        self.assertIn("title", res.json()["error"])

    def test_there_is_a_limit_on_active_notes(self):
        for i in range(20):
            _note(self.lea, title=f"Note {i}")
        self.assertEqual(self.add().status_code, 409)
        _note(self.lea, title="Old one", status="Resolved", resolved_on=_day(-5))  # recovered ones don't count
        self.assertEqual(HealthNote.objects.filter(status="Active").count(), 20)

    def test_editing_recovering_and_bringing_back(self):
        note_id = self.add().json()["active"][0]["id"]
        res = self.patch(note_id, {"severity": "Moderate", "details": "Light squats are fine now."})
        self.assertEqual(res.json()["active"][0]["severity"], "Moderate")

        res = self.patch(note_id, {"status": "Resolved"})
        self.assertEqual(res.json()["active"], [])
        [recovered] = res.json()["recovered"]
        self.assertEqual((recovered["status"], recovered["resolvedOn"]), ("Resolved", str(timezone.localdate())))

        res = self.patch(note_id, {"status": "Active"})
        self.assertEqual((len(res.json()["active"]), res.json()["active"][0]["resolvedOn"]), (1, None))

    def test_bringing_back_a_note_that_now_has_a_twin_is_refused(self):
        old = _note(self.lea, title="Torn ACL, left knee", status="Resolved", resolved_on=_day(-10))
        self.add()
        self.assertEqual(self.patch(old.id, {"status": "Active"}).status_code, 400)

    def test_deleting_removes_it_for_good(self):
        note_id = self.add().json()["active"][0]["id"]
        res = self.client.delete(f"/api/members/me/health/{note_id}")
        self.assertEqual((res.status_code, res.json()["active"]), (200, []))
        self.assertFalse(HealthNote.objects.exists())

    def test_nothing_to_declare(self):
        res = self.client.post("/api/members/me/health/confirm")
        self.assertEqual((res.status_code, res.json()["reviewedOn"]), (200, str(timezone.localdate())))

    def test_old_information_asks_for_a_review(self):
        HealthDeclaration.objects.create(member=self.lea, reviewed_at=timezone.now() - timedelta(days=200))
        self.assertTrue(self.client.get("/api/members/me/health").json()["needsReview"])
        self.assertFalse(self.client.post("/api/members/me/health/confirm").json()["needsReview"])

    def test_nobody_touches_someone_elses_notes(self):
        theirs = _note(self.sami)
        self.assertEqual(self.patch(theirs.id, {"title": "Hacked"}).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/members/me/health/{theirs.id}").status_code, 404)
        self.assertEqual(self.client.get("/api/members/me/health").json()["active"], [])
        theirs.refresh_from_db()
        self.assertEqual(theirs.title, "Lower back pain")

    def test_members_only(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/members/me/health").status_code, 401)
        _coach("hadi")
        staff_login(self.client, "hadi", PASSWORD)
        self.assertEqual(self.add().status_code, 401)
        self.assertEqual(self.client.post("/api/members/me/health/confirm").status_code, 401)

    def test_notes_are_exported_and_erased_with_the_member(self):
        self.add()
        export = self.client.get("/api/members/me/export")
        self.assertIn(b"Torn ACL, left knee", export.content)
        res = self.client.post("/api/members/me/delete", {"password": PASSWORD, "confirm": "DELETE"},
                               content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(HealthNote.objects.exists())
        self.assertFalse(HealthDeclaration.objects.exists())


# User story: "As a coach, I want to view a client's health restrictions and
# injuries before starting a session, so that I can adapt the workout safely."
class CoachHealthBriefingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _staff("bm", ["manage_class_schedule", "manage_members", "view_all_branches"], branch="Hamra")
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        cls.hadi = _coach("hadi")
        cls.rita = _coach("rita")
        cls.lea = _member("Lea Haddad", "lea")      # two active notes
        cls.sami = _member("Sami Khoury", "sami")   # nothing to declare
        cls.nour = _member("Nour Saad", "nour")     # never filled it in
        cls.spin = _class("Spinning", cls.hadi, _day(1), start="18:00")
        _note(cls.lea, title="Lower back pain", severity="Mild")
        _note(cls.lea, title="Torn ACL, left knee", severity="Severe", details="No jumping.")
        _note(cls.lea, title="Sprained wrist", status="Resolved", resolved_on=_day(-10))
        _note(cls.lea, title="Broken toe", status="Resolved", resolved_on=_day(-200))
        HealthDeclaration.objects.create(member=cls.sami)

    def setUp(self):
        for member in (self.lea, self.sami, self.nour):
            _book(member, self.spin)
        staff_login(self.client, "hadi", PASSWORD)

    def class_briefing(self, gym_class=None):
        return self.client.get(f"/api/health-notes/classes/{(gym_class or self.spin).id}")

    def views_logged(self):
        return AuditLog.objects.filter(action=AuditLog.Action.HEALTH_VIEWED)

    # --- a class ---
    def test_the_class_briefing_sorts_members_by_what_the_coach_needs_to_know(self):
        res = self.class_briefing()
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["booked"], 3)
        [lea] = body["restricted"]
        self.assertEqual((lea["name"], lea["activeCount"], lea["severity"]), ("Lea Haddad", 2, "Severe"))
        # Most limiting first; a recent recovery is mentioned, an old one isn't.
        self.assertEqual([n["title"] for n in lea["active"]], ["Torn ACL, left knee", "Lower back pain"])
        self.assertEqual(lea["active"][0]["details"], "No jumping.")
        self.assertEqual([n["title"] for n in lea["recentlyRecovered"]], ["Sprained wrist"])
        self.assertEqual([m["name"] for m in body["undeclared"]], ["Nour Saad"])
        self.assertEqual([m["name"] for m in body["clear"]], ["Sami Khoury"])

    def test_someone_who_cancelled_their_spot_is_not_in_it(self):
        ClassBooking.objects.filter(member=self.lea).update(status=ClassBooking.Status.CANCELLED)
        body = self.class_briefing().json()
        self.assertEqual((body["booked"], body["restricted"]), (2, []))

    def test_only_the_class_coach_sees_it(self):
        for username in ("rita", "bm", "desk"):
            staff_login(self.client, username, PASSWORD)
            self.assertEqual(self.class_briefing().status_code, 403, username)
        self.client.logout()
        self.assertEqual(self.class_briefing().status_code, 401)
        _member_login(self.client, "sami")
        self.assertEqual(self.class_briefing().status_code, 401)
        self.assertFalse(self.views_logged().exists())

    def test_a_coach_who_takes_over_the_class_sees_it_and_the_old_one_stops(self):
        GymClass.objects.filter(pk=self.spin.pk).update(coach=self.rita)
        self.assertEqual(self.class_briefing().status_code, 403)
        staff_login(self.client, "rita", PASSWORD)
        self.assertEqual(self.class_briefing().status_code, 200)

    def test_not_for_a_cancelled_class_a_missing_one_or_one_long_over(self):
        self.assertEqual(self.client.get("/api/health-notes/classes/999999").status_code, 404)
        GymClass.objects.filter(pk=self.spin.pk).update(status=GymClass.Status.CANCELLED)
        self.assertEqual(self.class_briefing().status_code, 409)
        old = _class("Spinning", self.hadi, _day(-2), start="09:00")
        _book(self.lea, old)
        self.assertEqual(self.class_briefing(old).status_code, 409)
        # ...but still open the day after, like attendance.
        recent = _class("Spinning", self.hadi, _day(-1), start="23:00", minutes=59)
        self.assertEqual(self.class_briefing(recent).status_code, 200)

    def test_an_empty_class_has_an_empty_briefing(self):
        empty = _class("Spinning", self.hadi, _day(3))
        body = self.class_briefing(empty).json()
        self.assertEqual((body["booked"], body["restricted"], body["undeclared"], body["clear"]), (0, [], [], []))

    def test_information_not_confirmed_for_months_is_flagged(self):
        HealthDeclaration.objects.filter(member=self.sami).update(reviewed_at=timezone.now() - timedelta(days=200))
        [sami] = self.class_briefing().json()["clear"]
        self.assertTrue(sami["stale"])

    # --- a private session ---
    def test_the_private_session_briefing(self):
        session = _pt(self.hadi, self.lea, 1)
        res = self.client.get(f"/api/health-notes/pt-sessions/{session.id}")
        self.assertEqual(res.status_code, 200, res.content)
        member = res.json()["member"]
        self.assertEqual((member["name"], member["status"], member["activeCount"]), ("Lea Haddad", "restrictions", 2))
        self.assertEqual(res.json()["session"]["memberName"], "Lea Haddad")

    def test_private_session_briefing_rules(self):
        theirs = _pt(self.rita, self.lea, 1, start="12:00")
        cancelled = _pt(self.hadi, self.lea, 2, status=PTSession.Status.CANCELLED)
        long_ago = _pt(self.hadi, self.lea, -40)
        last_week = _pt(self.hadi, self.lea, -7)
        get = lambda s: self.client.get(f"/api/health-notes/pt-sessions/{s.id}").status_code  # noqa: E731
        self.assertEqual([get(theirs), get(cancelled), get(long_ago), get(last_week)], [403, 409, 409, 200])
        self.assertEqual(self.client.get("/api/health-notes/pt-sessions/999999").status_code, 404)

    # --- from My Clients ---
    def test_a_client_by_id_needs_a_session_with_this_coach(self):
        dana = _member("Dana Aoun", "dana")
        _note(dana)
        self.assertEqual(self.client.get(f"/api/health-notes/members/{dana.id}").status_code, 403)
        self.assertEqual(self.client.get("/api/health-notes/members/999999").status_code, 403)
        _pt(self.hadi, dana, -40)   # too long ago
        self.assertEqual(self.client.get(f"/api/health-notes/members/{dana.id}").status_code, 403)
        _pt(self.hadi, dana, 3)
        res = self.client.get(f"/api/health-notes/members/{dana.id}")
        self.assertEqual((res.status_code, res.json()["member"]["status"]), (200, "restrictions"))
        # A class booking counts too (Lea has no private session with Hadi).
        self.assertEqual(self.client.get(f"/api/health-notes/members/{self.lea.id}").status_code, 200)

    def test_freezing_a_membership_ends_the_coachs_access(self):
        _pt(self.hadi, self.lea, 3)
        _member_login(self.client, "lea")
        self.assertEqual(self.client.post("/api/members/me/freeze").status_code, 200)
        staff_login(self.client, "hadi", PASSWORD)
        self.assertEqual(self.client.get(f"/api/health-notes/members/{self.lea.id}").status_code, 403)
        self.assertEqual(self.class_briefing().json()["booked"], 2)

    def test_the_client_list_carries_a_badge_or_nothing(self):
        _pt(self.hadi, self.lea, 3)
        _pt(self.hadi, self.nour, -40)
        ClassBooking.objects.filter(member=self.nour).update(status=ClassBooking.Status.CANCELLED)
        clients = {c["name"]: c["health"] for c in self.client.get("/api/progress/clients").json()["results"]}
        self.assertEqual(clients["Lea Haddad"], {"status": "restrictions", "activeCount": 2, "severity": "Severe", "stale": False})
        self.assertIsNone(clients["Nour Saad"])

    # --- the schedule ---
    def test_the_schedule_flags_each_session(self):
        session = _pt(self.hadi, self.nour, 1, start="08:00")
        past = _class("Yoga", self.hadi, _day(-3), start="07:00")
        seen = {}
        for week in {str(_day(1)), str(_day(-3))}:
            health = self.client.get("/api/classes/me/schedule", {"week": week}).json()["health"]
            seen.setdefault("classes", {}).update(health["classes"])
            seen.setdefault("ptSessions", {}).update(health["ptSessions"])
        self.assertEqual(seen["classes"][str(self.spin.id)], {"booked": 3, "restricted": 1, "undeclared": 1, "severe": 1})
        self.assertEqual(seen["ptSessions"][str(session.id)]["status"], "undeclared")
        self.assertNotIn(str(past.id), seen["classes"])
        self.assertFalse(self.views_logged().exists())  # counts only - nobody's notes were opened

    # --- the audit trail ---
    def test_opening_notes_is_logged_once_a_day_without_the_notes(self):
        session = _pt(self.hadi, self.lea, 1)
        for _ in range(2):
            self.class_briefing()
            self.client.get(f"/api/health-notes/pt-sessions/{session.id}")
            self.client.get(f"/api/health-notes/members/{self.lea.id}")
        entries = list(self.views_logged().order_by("id"))
        self.assertEqual([(e.target_type, e.target_label) for e in entries], [("gymclass", "Spinning"), ("member", "Lea Haddad")])
        self.assertEqual(entries[0].actor_name, "Hadi")
        for entry in entries:
            self.assertNotIn("ACL", entry.summary + str(entry.details))

    def test_the_coach_can_only_read(self):
        note = HealthNote.objects.filter(member=self.lea).first()
        for method in ("post", "put", "patch", "delete"):
            res = getattr(self.client, method)(f"/api/health-notes/members/{self.lea.id}", {}, content_type="application/json")
            self.assertEqual(res.status_code, 405, method)
        self.assertEqual(self.client.patch(f"/api/members/me/health/{note.id}", {"title": "Fine"},
                                           content_type="application/json").status_code, 401)
