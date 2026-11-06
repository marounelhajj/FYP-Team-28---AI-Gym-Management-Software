from datetime import time, timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from administration.models import StaffAccount
from administration.testing import staff_login
from billing.models import Payment, PaymentMethod
from classes.models import ClassBooking, GymClass, PTSession
from classes.rules import local_datetime
from classes.tests import PASSWORD, _book, _class, _coach, _day, _member, _member_login, _staff
from members.models import Member
from plans.models import BranchPromotion, MembershipPlan

from . import reminders
from .models import MemberNotification, NotificationSettings, SentReminder

Kind = MemberNotification.Kind


def _at(day_offset, clock):
    return local_datetime(_day(day_offset), time.fromisoformat(clock))


# User story: "As a member, I want to receive notifications before an upcoming
# class or when my membership is about to renew, so that I don't miss sessions
# or get charged unexpectedly."
class ClassReminderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _staff("bm", ["manage_class_schedule", "manage_members"], branch="Hamra")
        cls.hadi = _coach("hadi")
        cls.rita = _coach("rita")
        cls.lea = _member("Lea Haddad", "lea")
        cls.sami = _member("Sami Khoury", "sami")
        # Two days ahead at 18:00, so "the day before" is tomorrow 18:00.
        cls.spin = _class("Spinning", cls.hadi, _day(2), start="18:00", room="Cycle Studio")

    def setUp(self):
        self.booking = _book(self.lea, self.spin)

    def run_at(self, moment):
        with self.captureOnCommitCallbacks(execute=True):
            return reminders.send_due(moment)

    def notes(self, member=None):
        return list(MemberNotification.objects.filter(recipient=member or self.lea).order_by("id"))

    def test_nothing_goes_out_before_it_is_due(self):
        self.assertEqual(self.run_at(_at(1, "17:00")), 0)
        self.assertEqual(self.notes(), [])

    def test_the_day_before_and_an_hour_before_by_default(self):
        self.assertEqual(self.run_at(_at(1, "18:00")), 1)
        day_before = self.notes()[0]
        self.assertEqual((day_before.kind, day_before.title), (Kind.CLASS_REMINDER, "Reminder: Spinning tomorrow at 18:00"))
        self.assertIn("Spinning with Hadi", day_before.message)
        self.assertIn("Cycle Studio, Hamra", day_before.message)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["lea@example.com"])

        # Running again (the job runs every minute) sends nothing new.
        self.assertEqual(self.run_at(_at(1, "18:01")), 0)

        self.assertEqual(self.run_at(_at(2, "17:00")), 1)
        hour_before = self.notes()[1]
        self.assertEqual(hour_before.title, "Reminder: Spinning today at 18:00")
        self.assertIn("starts in 60 minutes", hour_before.message)
        self.assertEqual(self.run_at(_at(2, "17:30")), 0)
        self.assertEqual(len(self.notes()), 2)

    def test_after_a_gap_only_the_latest_reminder_goes_out(self):
        # The server was off all day: one up-to-date reminder, not a stale "tomorrow" one too.
        self.assertEqual(self.run_at(_at(2, "17:20")), 1)
        [only] = self.notes()
        self.assertIn("starts in 40 minutes", only.message)
        self.assertEqual(self.run_at(_at(2, "17:25")), 0)
        handled = set(SentReminder.objects.values_list("key", flat=True))
        self.assertEqual({k.rsplit(":", 1)[1] for k in handled}, {"1440", "60"})

    def test_no_reminder_whose_time_had_passed_when_they_booked(self):
        self.booking.booked_at = _at(2, "09:00")  # booked the same morning
        self.booking.save()
        self.assertEqual(self.run_at(_at(2, "09:05")), 0)
        self.assertEqual(self.run_at(_at(2, "17:00")), 1)
        self.assertIn("today at 18:00", self.notes()[0].title)

    def test_cancelled_bookings_cancelled_classes_and_started_classes_get_none(self):
        self.booking.status = ClassBooking.Status.CANCELLED
        self.booking.save()
        _book(self.sami, self.spin)
        GymClass.objects.filter(pk=self.spin.pk).update(status=GymClass.Status.CANCELLED)
        self.assertEqual(self.run_at(_at(1, "18:00")), 0)
        GymClass.objects.filter(pk=self.spin.pk).update(status=GymClass.Status.SCHEDULED)
        self.assertEqual(self.run_at(_at(2, "18:05")), 0)  # already started
        self.assertEqual(self.notes(self.sami), [])

    def test_frozen_members_get_no_class_reminders(self):
        Member.objects.filter(pk=self.lea.pk).update(status=Member.Status.FROZEN)
        self.assertEqual(self.run_at(_at(1, "18:00")), 0)

    def test_members_choose_their_own_reminders(self):
        NotificationSettings.objects.create(member=self.lea, class_day_before=False, class_minutes_before=120)
        self.assertEqual(self.run_at(_at(1, "18:00")), 0)
        self.assertEqual(self.run_at(_at(2, "16:00")), 1)
        self.assertIn("in about 2 hours", self.notes()[0].message)
        self.assertEqual(self.run_at(_at(2, "17:00")), 0)  # no 1-hour one any more

    def test_turning_reminders_off(self):
        NotificationSettings.objects.create(member=self.lea, class_day_before=False, class_minutes_before=0)
        self.assertEqual(self.run_at(_at(2, "17:30")), 0)

    def test_a_reminder_further_out_never_follows_a_closer_one(self):
        self.assertEqual(self.run_at(_at(2, "17:00")), 1)  # the 1-hour one (the day-before one is skipped)
        NotificationSettings.objects.create(member=self.lea, class_minutes_before=180)
        self.assertEqual(self.run_at(_at(2, "17:10")), 0)

    def test_email_can_be_turned_off_but_the_app_still_shows_it(self):
        NotificationSettings.objects.create(member=self.lea, email=False)
        self.assertEqual(self.run_at(_at(1, "18:00")), 1)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNone(self.notes()[0].emailed_at)

    def test_two_runs_at_once_remind_only_once(self):
        moment = _at(1, "18:00")
        due = reminders._schedule({1440: moment}, None, moment, set())[0]
        base = f"class:{self.booking.id}:{reminders._stamp(self.spin.starts_at)}"
        self.assertTrue(reminders._send(self.lea, "class", base, due, Kind.CLASS_REMINDER, "t", "m"))
        self.assertFalse(reminders._send(self.lea, "class", base, due, Kind.CLASS_REMINDER, "t", "m"))
        self.assertEqual(len(self.notes()), 1)

    def test_a_moved_class_tells_everyone_booked_and_reminds_for_the_new_time(self):
        self.assertEqual(self.run_at(_at(1, "18:00")), 1)
        staff_login(self.client, "bm", PASSWORD)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.patch(
                f"/api/classes/{self.spin.id}", {"startTime": "19:00", "room": "Studio B", "coachId": self.rita.id},
                content_type="application/json",
            )
        self.assertEqual(res.status_code, 200, res.content)
        changed = self.notes()[-1]
        self.assertEqual(changed.kind, Kind.CLASS_CHANGED)
        self.assertIn("19:00-20:00 (was", changed.message)
        self.assertIn("now in Studio B (was Cycle Studio)", changed.message)
        self.assertIn("Rita is coaching it instead of Hadi", changed.message)

        # The day-before reminder for 19:00 is new: the old one was for 18:00.
        self.assertEqual(self.run_at(_at(1, "19:00")), 1)
        self.assertIn("tomorrow at 19:00", self.notes()[-1].title)

    def test_editing_only_the_description_tells_nobody(self):
        staff_login(self.client, "bm", PASSWORD)
        res = self.client.patch(f"/api/classes/{self.spin.id}", {"description": "Bring water"}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(self.notes(), [])

    def test_private_sessions_are_reminded_too_and_a_gym_cancellation_is_told(self):
        starts = _at(2, "10:00")
        session = PTSession.objects.create(coach=self.hadi, member=self.sami, branch="Hamra", starts_at=starts,
                                           ends_at=starts + timedelta(hours=1))
        self.run_at(_at(2, "09:00"))
        [note] = self.notes(self.sami)
        self.assertEqual((note.kind, note.title), (Kind.PT_REMINDER, "Reminder: private training today at 10:00"))
        self.assertIn("with Hadi", note.message)

        staff_login(self.client, "bm", PASSWORD)
        res = self.client.post(f"/api/classes/pt-sessions/{session.id}/cancel", {"reason": "Coach is ill"},
                               content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        cancelled = self.notes(self.sami)[-1]
        self.assertEqual(cancelled.kind, Kind.PT_CANCELLED)
        self.assertIn("Reason: Coach is ill.", cancelled.message)


class RenewalReminderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.basic = MembershipPlan.objects.create(name="Basic", price=Decimal("25.00"), max_promo_discount_percent=50)
        cls.lea = _member("Lea Haddad", "lea", days_valid=7)

    def run_at(self, moment):
        with self.captureOnCommitCallbacks(execute=True):
            return reminders.send_due(moment)

    def notes(self, member=None):
        return list(MemberNotification.objects.filter(recipient=member or self.lea).order_by("id"))

    def expiring(self, days):
        Member.objects.filter(pk=self.lea.pk).update(subscription_expires_at=_day(days))

    def test_seven_days_before_at_nine_then_the_day_before(self):
        self.assertEqual(self.run_at(_at(0, "08:59")), 0)
        self.assertEqual(self.run_at(_at(0, "09:00")), 1)
        note = self.notes()[0]
        self.assertEqual(note.kind, Kind.RENEWAL_REMINDER)
        self.assertEqual(note.title, f"Membership renewal due in 7 days ({_day(7):%a %d %b})")
        self.assertIn("Renewing for 1 month costs $25.00.", note.message)
        self.assertIn("Nothing is charged automatically", note.message)
        self.assertIn("No payment method is on file", note.message)
        self.assertEqual(len(mail.outbox), 1)

        self.assertEqual(self.run_at(_at(3, "09:00")), 0)
        self.assertEqual(self.run_at(_at(6, "09:00")), 1)
        self.assertTrue(self.notes()[1].title.startswith("Membership renewal due tomorrow"))
        self.assertEqual(self.run_at(_at(6, "12:00")), 0)

    def test_the_price_card_and_promotion_are_spelled_out(self):
        PaymentMethod.objects.create(member=self.lea, method="Card", card_last4="4242", card_expiry_month=1,
                                     card_expiry_year=_day(0).year)  # runs out before the renewal date
        payment = Payment.objects.create(member=self.lea, amount=Decimal("30.00"), method="Card", duration="1 Month",
                                         expires_at=_day(7))
        Payment.objects.filter(pk=payment.pk).update(paid_at=timezone.now() - timedelta(days=23))
        BranchPromotion.objects.create(plan=self.basic, branch="Hamra", name="Winter Deal", discount_type="Percent",
                                       discount_value=Decimal("20"), start_date=_day(-1), end_date=_day(30))
        self.run_at(_at(0, "09:00"))
        message = self.notes()[0].message
        self.assertIn("costs $20.00 with the Winter Deal promotion (you paid $30.00 last time).", message)
        self.assertIn("On file: Card ending 4242.", message)
        self.assertIn("That card expires 01/", message)

    def test_a_yearly_member_is_quoted_a_year(self):
        payment = Payment.objects.create(member=self.lea, amount=Decimal("280.00"), method="Cash", duration="1 Year",
                                         expires_at=_day(7))
        Payment.objects.filter(pk=payment.pk).update(paid_at=timezone.now() - timedelta(days=358))
        self.run_at(_at(0, "09:00"))
        self.assertIn("Renewing for 1 year costs $280.00.", self.notes()[0].message)

    def test_a_plan_no_longer_offered_is_explained(self):
        MembershipPlan.objects.filter(pk=self.basic.pk).update(is_active=False)
        self.run_at(_at(0, "09:00"))
        self.assertIn("The Basic plan isn't offered any more", self.notes()[0].message)

    def test_renewing_early_moves_the_reminders_to_the_new_date(self):
        self.assertEqual(self.run_at(_at(0, "09:00")), 1)
        self.expiring(37)  # renewed: a month more
        self.assertEqual(self.run_at(_at(6, "09:00")), 0)
        self.assertEqual(self.run_at(_at(30, "09:00")), 1)
        self.assertIn(f"{_day(37):%a %d %b}", self.notes()[-1].title)

    def test_no_reminder_right_after_paying(self):
        self.expiring(3)
        Payment.objects.create(member=self.lea, amount=Decimal("25.00"), method="Cash", duration="1 Month",
                               expires_at=_day(3))  # paid just now, after today's 09:00
        self.assertEqual(self.run_at(_at(0, "23:00")), 0)

    def test_a_frozen_membership_still_hears_when_it_runs_out(self):
        Member.objects.filter(pk=self.lea.pk).update(status=Member.Status.FROZEN)
        self.run_at(_at(0, "09:00"))
        self.assertIn("membership is frozen and runs until", self.notes()[0].message)

    def test_cancelled_or_already_expired_get_nothing(self):
        Member.objects.filter(pk=self.lea.pk).update(status=Member.Status.CANCELLED)
        self.assertEqual(self.run_at(_at(0, "09:00")), 0)
        Member.objects.filter(pk=self.lea.pk).update(status=Member.Status.ACTIVE, subscription_expires_at=_day(-1))
        self.assertEqual(self.run_at(_at(0, "09:00")), 0)

    def test_on_the_last_day_it_says_today(self):
        self.expiring(0)
        self.run_at(_at(0, "09:00"))
        self.assertTrue(self.notes()[0].title.startswith("Membership renewal due today"))

    def test_members_pick_how_early_or_turn_it_off(self):
        NotificationSettings.objects.create(member=self.lea, renewal_days_before=3)
        self.assertEqual(self.run_at(_at(0, "09:00")), 0)
        self.assertEqual(self.run_at(_at(4, "09:00")), 1)
        NotificationSettings.objects.filter(member=self.lea).update(renewal_days_before=0)
        self.assertEqual(self.run_at(_at(6, "09:00")), 0)

    def test_the_command_sends_what_is_due(self):
        out = StringIO()
        with mock.patch("notifications.reminders.timezone.now", return_value=_at(0, "09:30")):
            call_command("send_reminders", stdout=out)
        self.assertEqual(out.getvalue().strip(), "Sent 1 reminder.")


class ReminderSettingsApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MembershipPlan.objects.create(name="Basic", price=Decimal("25.00"))
        cls.hadi = _coach("hadi")
        cls.lea = _member("Lea Haddad", "lea", days_valid=10)
        cls.spin = _class("Spinning", cls.hadi, _day(2), start="18:00")

    def setUp(self):
        _member_login(self.client, "lea")

    def test_defaults_and_what_is_coming(self):
        _book(self.lea, self.spin)
        body = self.client.get("/api/members/me/reminders").json()
        self.assertEqual(body["settings"], {"classDayBefore": True, "classMinutesBefore": 60, "renewalDaysBefore": 7,
                                            "email": True})
        self.assertEqual(body["choices"]["classMinutesBefore"], [0, 30, 60, 120, 180])
        self.assertEqual(body["emailAddress"], "lea@example.com")
        upcoming = [(u["kind"], u["sendAt"]) for u in body["upcoming"]]
        self.assertEqual(upcoming[0], ("class", f"{_day(1)} 18:00"))
        self.assertIn(("renewal", f"{_day(3)} 09:00"), upcoming)

    def test_a_renewal_months_away_is_still_shown(self):
        Member.objects.filter(pk=self.lea.pk).update(subscription_expires_at=_day(60))
        upcoming = self.client.get("/api/members/me/reminders").json()["upcoming"]
        self.assertEqual([(u["kind"], u["sendAt"]) for u in upcoming], [("renewal", f"{_day(53)} 09:00")])
        self.assertEqual(reminders.send_due(_at(0, "09:00")), 0)  # but nothing is sent yet

    def test_changing_settings(self):
        res = self.client.patch("/api/members/me/reminders", {"classMinutesBefore": 30, "email": False},
                                content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["settings"]["classMinutesBefore"], 30)
        prefs = NotificationSettings.objects.get(member=self.lea)
        self.assertEqual((prefs.class_minutes_before, prefs.email, prefs.class_day_before), (30, False, True))

    def test_only_the_offered_choices(self):
        res = self.client.put("/api/members/me/reminders", {"classMinutesBefore": 45, "renewalDaysBefore": 100},
                              content_type="application/json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("classMinutesBefore", res.json()["error"])
        self.assertIn("renewalDaysBefore", res.json()["error"])
        self.assertFalse(NotificationSettings.objects.exists())

    def test_turning_everything_off_empties_whats_coming(self):
        _book(self.lea, self.spin)
        res = self.client.patch("/api/members/me/reminders",
                                {"classDayBefore": False, "classMinutesBefore": 0, "renewalDaysBefore": 0},
                                content_type="application/json")
        self.assertEqual(res.json()["upcoming"], [])

    def test_members_only(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/members/me/reminders").status_code, 401)
        _staff("desk", ["manage_members"], branch="Hamra", job_title=StaffAccount.JobTitle.RECEPTIONIST)
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.client.patch("/api/members/me/reminders", {"email": False},
                                           content_type="application/json").status_code, 401)

    def test_settings_are_exported_and_erased(self):
        self.client.patch("/api/members/me/reminders", {"renewalDaysBefore": 14}, content_type="application/json")
        export = self.client.get("/api/members/me/export")
        self.assertIn(b'"renewalDaysBefore": 14', export.content)
        res = self.client.post("/api/members/me/delete", {"password": PASSWORD, "confirm": "DELETE"},
                               content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(NotificationSettings.objects.filter(member=self.lea).exists())
