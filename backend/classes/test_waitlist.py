from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from members.models import Member
from notifications.models import MemberNotification

from .models import ClassBooking, GymClass, PTSession, WaitlistEntry
from .tests import PASSWORD, _book, _class, _coach, _day, _member, _member_login, _staff, _type
from .waitlist import MAX_WAITLISTS, close_started, fill


# User story: "As a member, I want to join a waitlist for a full class and be
# notified automatically when a spot opens up, so that I don't have to keep
# checking manually."
class WaitlistTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _staff("bm", ["manage_class_schedule", "manage_members"], branch="Hamra")
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        cls.hadi = _coach("hadi")
        cls.rita = _coach("rita")
        cls.lea = _member("Lea Haddad", "lea")      # holds the only spot
        cls.sami = _member("Sami Khoury", "sami")   # first in line
        cls.nour = _member("Nour Saad", "nour")     # second in line
        cls.jad = _member("Jad Tannous", "jad", branch="Jnah")
        cls.spin = _class("Spinning", cls.hadi, _day(1), start="18:00", capacity=1)
        cls.yoga = _class("Yoga", cls.rita, _day(1), start="18:30", capacity=5)  # overlaps Spinning

    def setUp(self):
        self.lea_booking = _book(self.lea, self.spin)
        _member_login(self.client, "sami")

    # --- helpers ---
    def login(self, username):
        _member_login(self.client, username)

    def join(self, gym_class):
        return self.client.post(f"/api/members/me/classes/{gym_class.id}/waitlist")

    def leave(self, gym_class):
        return self.client.post(f"/api/members/me/classes/{gym_class.id}/waitlist/leave")

    def cancel_my_spot(self, gym_class):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"/api/members/me/classes/{gym_class.id}/cancel")

    def queue(self, *members, gym_class=None):
        for member in members:
            WaitlistEntry.objects.create(gym_class=gym_class or self.spin, member=member)

    def entry(self, member, gym_class=None):
        return WaitlistEntry.objects.filter(member=member, gym_class=gym_class or self.spin).latest("id")

    def booked(self, member, gym_class=None):
        return ClassBooking.objects.filter(member=member, gym_class=gym_class or self.spin, status="Booked").exists()

    def notes(self, member):
        return list(MemberNotification.objects.filter(recipient=member).order_by("id").values_list("kind", flat=True))

    # --- joining ---
    def test_a_member_joins_the_waitlist_of_a_full_class_and_sees_their_place(self):
        res = self.join(self.spin)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["myWaitlist"]["position"], res.json()["waitlistCount"]), (1, 1))
        self.login("nour")
        self.assertEqual(self.join(self.spin).json()["myWaitlist"]["position"], 2)
        week = self.client.get(f"/api/members/me/classes?week={_day(1)}").json()
        spin = next(c for c in week["classes"] if c["id"] == self.spin.id)
        self.assertEqual((spin["myWaitlist"]["position"], spin["waitlistCount"], spin["spotsLeft"]), (2, 2, 0))
        self.assertEqual([(w["name"], w["myWaitlist"]["position"]) for w in week["waitlists"]], [("Spinning", 2)])

    def test_joining_is_refused_when_it_could_never_work(self):
        self.assertIn("book it instead", self.join(self.yoga).json()["error"])        # not full
        self.login("lea")
        self.assertIn("already reserved", self.join(self.spin).json()["error"])       # has a spot
        self.login("sami")
        self.join(self.spin)
        self.assertIn("already on the waitlist", self.join(self.spin).json()["error"])
        self.login("jad")
        self.assertEqual(self.join(self.spin).status_code, 403)                       # another branch
        self.assertEqual(self.client.post("/api/members/me/classes/999999/waitlist").status_code, 404)

    def test_joining_needs_a_membership_that_covers_the_class(self):
        Member.objects.filter(id=self.sami.id).update(status=Member.Status.FROZEN)
        self.assertIn("frozen", self.join(self.spin).json()["error"])
        Member.objects.filter(id=self.sami.id).update(status=Member.Status.ACTIVE, subscription_expires_at=timezone.localdate())
        self.assertIn("renew it", self.join(self.spin).json()["error"])

    def test_no_waitlist_for_a_class_that_started_or_was_cancelled(self):
        now = timezone.now()
        running = GymClass.objects.create(name="HIIT", class_type=_type("HIIT"), coach=self.rita, branch="Hamra", capacity=1,
                                          starts_at=now - timedelta(minutes=5), ends_at=now + timedelta(minutes=55))
        self.assertIn("already started", self.join(running).json()["error"])
        GymClass.objects.filter(id=self.spin.id).update(status=GymClass.Status.CANCELLED)
        self.assertIn("cancelled", self.join(self.spin).json()["error"])

    def test_no_waitlist_for_a_class_you_could_not_attend_anyway(self):
        _book(self.sami, _class("Boxing", self.rita, _day(1), start="18:15", capacity=5))
        self.assertIn("can't take two classes", self.join(self.spin).json()["error"])
        starts = self.spin.starts_at
        PTSession.objects.create(coach=self.rita, member=self.nour, branch="Hamra", starts_at=starts,
                                 ends_at=starts + timedelta(hours=1))
        self.login("nour")
        self.assertIn("private training session", self.join(self.spin).json()["error"])

    def test_one_member_can_only_wait_for_so_many_classes(self):
        for i in range(MAX_WAITLISTS):
            full = _class(f"Class {i}", self.rita, _day(2 + i), capacity=1)
            _book(self.lea, full)
            self.assertEqual(self.join(full).status_code, 201)
        res = self.join(self.spin)
        self.assertEqual(res.status_code, 409)
        self.assertIn(f"up to {MAX_WAITLISTS} waitlists", res.json()["error"])

    def test_leaving_the_waitlist_moves_everyone_up(self):
        self.join(self.spin)
        self.login("nour")
        self.join(self.spin)
        self.login("sami")
        res = self.leave(self.spin)
        self.assertEqual((res.status_code, res.json()["myWaitlist"]), (200, None))
        self.assertEqual(self.entry(self.sami).status, "Left")
        self.login("nour")
        week = self.client.get(f"/api/members/me/classes?week={_day(1)}").json()
        self.assertEqual(next(c for c in week["classes"] if c["id"] == self.spin.id)["myWaitlist"]["position"], 1)
        self.login("sami")
        self.assertEqual(self.leave(self.spin).status_code, 404)  # only once

    # --- a spot opens: first in line is booked and told ---
    def test_a_cancellation_books_the_first_in_line_and_tells_them(self):
        self.queue(self.sami, self.nour)
        self.login("lea")
        res = self.cancel_my_spot(self.spin)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(self.booked(self.sami))
        booking = ClassBooking.objects.get(member=self.sami, gym_class=self.spin, status="Booked")
        self.assertTrue(booking.from_waitlist)
        self.assertEqual((self.entry(self.sami).status, self.entry(self.sami).booking_id), ("Booked", booking.id))
        self.assertEqual(self.entry(self.nour).status, "Waiting")  # still waiting, now first
        self.assertEqual(self.notes(self.sami), ["waitlist_spot"])
        self.assertEqual(self.notes(self.nour), [])

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["sami@example.com"])
        self.assertIn("You're in: Spinning", email.subject)
        self.assertIn("Hi Sami", email.body)
        self.assertIsNotNone(MemberNotification.objects.get(recipient=self.sami).emailed_at)

    def test_the_freed_spot_is_never_left_for_someone_else_to_grab(self):
        self.queue(self.sami)
        self.login("lea")
        self.cancel_my_spot(self.spin)
        self.login("nour")
        res = self.client.post(f"/api/members/me/classes/{self.spin.id}/book")
        self.assertEqual(res.status_code, 409)
        self.assertIn("full", res.json()["error"])

    def test_the_front_desk_removing_a_booking_also_goes_to_the_waitlist(self):
        self.queue(self.sami)
        staff_login(self.client, "desk", PASSWORD)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(f"/api/classes/{self.spin.id}/bookings/{self.lea_booking.id}/cancel")
        self.assertEqual((res.status_code, res.json()["class"]["spotsLeft"]), (200, 0))
        self.assertTrue(self.booked(self.sami))
        self.assertEqual(len(mail.outbox), 1)
        detail = self.client.get(f"/api/classes/{self.spin.id}").json()
        self.assertEqual(detail["waitlist"], [])
        roster = [(r["memberName"], r["status"], r["fromWaitlist"]) for r in detail["roster"]]
        self.assertIn(("Sami Khoury", "Booked", True), roster)

    def test_a_manager_adding_spots_fills_them_from_the_waitlist_in_order(self):
        self.queue(self.sami, self.nour)
        staff_login(self.client, "bm", PASSWORD)
        res = self.client.patch(f"/api/classes/{self.spin.id}", {"capacity": 3}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(self.booked(self.sami) and self.booked(self.nour))
        self.assertEqual(res.json()["classes"][0]["spotsLeft"], 0)

    def test_raising_a_class_types_maximum_fills_from_the_waitlist(self):
        self.queue(self.sami)
        staff_login(self.client, "bm", PASSWORD)
        GymClass.objects.filter(id=self.spin.id).update(capacity=self.spin.class_type.max_capacity)
        for i in range(self.spin.class_type.max_capacity - 1):
            _book(_member(f"Filler {i}", f"filler{i}"), self.spin)
        res = self.client.patch(f"/api/classes/types/{self.spin.class_type_id}",
                                {"maxCapacity": self.spin.class_type.max_capacity + 1}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(self.booked(self.sami))

    def test_a_frozen_membership_gives_its_spot_to_the_waitlist(self):
        self.queue(self.sami)
        self.login("lea")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/api/members/me/freeze")
        self.assertTrue(self.booked(self.sami))
        self.assertFalse(self.booked(self.lea))

    def test_someone_who_can_no_longer_take_the_spot_is_skipped_and_told_why(self):
        self.queue(self.sami, self.nour)
        Member.objects.filter(id=self.sami.id).update(status=Member.Status.FROZEN)
        self.login("lea")
        self.cancel_my_spot(self.spin)
        self.assertFalse(self.booked(self.sami))
        self.assertEqual(self.entry(self.sami).status, "Skipped")
        self.assertIn("frozen", self.entry(self.sami).note)
        self.assertTrue(self.booked(self.nour))
        self.assertEqual(self.notes(self.sami), ["waitlist_skipped"])
        self.assertEqual(self.notes(self.nour), ["waitlist_spot"])

    def test_someone_now_busy_at_that_time_is_skipped(self):
        self.queue(self.sami, self.nour)
        _book(self.sami, self.yoga)  # booked something overlapping since joining
        self.login("lea")
        self.cancel_my_spot(self.spin)
        self.assertEqual(self.entry(self.sami).status, "Skipped")
        self.assertIn("Yoga", self.entry(self.sami).note)
        self.assertTrue(self.booked(self.nour))

    def test_getting_a_spot_ends_other_waitlists_at_the_same_time(self):
        full_yoga = _class("Yoga Flow", self.rita, _day(1), start="18:30", capacity=1)
        _book(self.lea, full_yoga)
        self.queue(self.sami)
        self.queue(self.sami, gym_class=full_yoga)
        self.login("lea")
        self.cancel_my_spot(self.spin)
        self.assertTrue(self.booked(self.sami))
        other = self.entry(self.sami, full_yoga)
        self.assertEqual(other.status, "Left")
        self.assertIn("Spinning", other.note)

    def test_booking_the_class_directly_ends_your_place_in_line(self):
        self.queue(self.sami)
        GymClass.objects.filter(id=self.spin.id).update(capacity=2)  # a spot appears with no fill() call
        self.assertEqual(self.client.post(f"/api/members/me/classes/{self.spin.id}/book").status_code, 201)
        self.assertEqual(self.entry(self.sami).status, "Booked")

    def test_fill_does_nothing_without_a_free_spot_or_anyone_waiting(self):
        self.queue(self.sami)
        self.assertEqual(fill(self.spin.id), [])  # still full
        self.assertEqual(fill(self.yoga.id), [])  # nobody waiting
        self.assertEqual(self.entry(self.sami).status, "Waiting")

    # --- the waitlist closes ---
    def test_cancelling_the_class_tells_everyone_booked_or_waiting(self):
        self.queue(self.sami)
        staff_login(self.client, "bm", PASSWORD)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f"/api/classes/{self.spin.id}/cancel", {"reason": "Coach is ill"}, content_type="application/json")
        self.assertEqual(self.entry(self.sami).status, "Closed")
        self.assertEqual(self.notes(self.sami), ["class_cancelled"])
        self.assertEqual(self.notes(self.lea), ["class_cancelled"])
        self.assertIn("Coach is ill", MemberNotification.objects.get(recipient=self.lea).message)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["lea@example.com", "sami@example.com"])

    def test_the_waitlist_closes_when_the_class_starts(self):
        self.queue(self.sami)
        GymClass.objects.filter(id=self.spin.id).update(
            starts_at=timezone.now() - timedelta(minutes=1), ends_at=timezone.now() + timedelta(minutes=59),
        )
        self.client.get("/api/members/me/classes")  # the lazy sweep
        self.assertEqual(self.entry(self.sami).status, "Closed")
        self.assertEqual(self.notes(self.sami), ["waitlist_closed"])
        close_started()  # a second sweep tells nobody twice
        self.assertEqual(self.notes(self.sami), ["waitlist_closed"])

    def test_freezing_takes_you_off_every_waitlist_quietly(self):
        self.queue(self.sami)
        self.client.post("/api/members/me/freeze")
        self.assertEqual(self.entry(self.sami).status, "Left")
        self.assertEqual(self.notes(self.sami), [])

    # --- notifications ---
    def test_a_member_reads_their_own_notifications(self):
        self.queue(self.sami)
        self.login("lea")
        self.cancel_my_spot(self.spin)
        self.assertEqual(self.client.get("/api/members/me/notifications").json()["results"], [])  # Lea's are empty
        self.login("sami")
        body = self.client.get("/api/members/me/notifications").json()
        self.assertEqual((body["unread"], body["results"][0]["kind"]), (1, "waitlist_spot"))
        note_id = body["results"][0]["id"]
        self.login("lea")
        self.assertEqual(self.client.post(f"/api/members/me/notifications/{note_id}/read").status_code, 404)
        self.login("sami")
        self.assertEqual(self.client.post(f"/api/members/me/notifications/{note_id}/read").status_code, 200)
        self.assertEqual(self.client.get("/api/members/me/notifications").json()["unread"], 0)
        self.client.post("/api/members/logout")
        self.assertEqual(self.client.get("/api/members/me/notifications").status_code, 401)

    def test_a_failing_mail_server_never_costs_anyone_their_spot(self):
        self.queue(self.sami)
        self.login("lea")
        with mock.patch("notifications.delivery.send_mail", side_effect=OSError("mail server down")):
            res = self.cancel_my_spot(self.spin)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(self.booked(self.sami))
        note = MemberNotification.objects.get(recipient=self.sami)
        self.assertIsNone(note.emailed_at)  # in the app, just not emailed

    # --- staff and privacy ---
    def test_staff_see_the_queue_in_order(self):
        self.queue(self.sami, self.nour)
        staff_login(self.client, "desk", PASSWORD)
        detail = self.client.get(f"/api/classes/{self.spin.id}").json()
        self.assertEqual([(w["position"], w["memberName"]) for w in detail["waitlist"]], [(1, "Sami Khoury"), (2, "Nour Saad")])
        day = self.client.get("/api/classes/day", {"date": str(_day(1))}).json()
        spin = next(c for c in day["classes"] if c["id"] == self.spin.id)
        self.assertEqual((spin["booked"], spin["waitlistCount"], spin["spotsLeft"]), (1, 2, 0))

    def test_waitlists_and_notifications_are_in_the_export_and_erased_with_the_member(self):
        self.queue(self.sami)
        MemberNotification.objects.create(recipient=self.sami, kind="waitlist_closed", title="t", message="m")
        export = self.client.get("/api/members/me/export").json()
        self.assertEqual([w["className"] for w in export["classWaitlists"]], ["Spinning"])
        self.assertEqual([n["title"] for n in export["notifications"]], ["t"])
        self.client.post("/api/members/me/delete", {"password": PASSWORD, "confirm": "DELETE"}, content_type="application/json")
        self.assertFalse(MemberNotification.objects.filter(recipient=self.sami).exists())
        self.assertEqual(self.entry(self.sami).status, "Left")
