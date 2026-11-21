from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from billing.models import Payment
from checkins.models import CheckIn
from classes import rules
from classes.models import ClassBooking, ClassType, GymClass, PTSession
from classes.rules import local_datetime
from members.models import Member
from plans.models import MembershipPlan

from . import points
from .models import LoyaltyPointEntry

PASSWORD = "ChangeMe123!"

# User story: "As a member, I want to earn loyalty points for attending
# sessions and referring friends, so that my consistency is rewarded."


def _staff(username, permissions, branch=None, job_title=StaffAccount.JobTitle.RECEPTIONIST):
    role = Role.objects.create(name=f"{username} role", permissions=permissions)
    account = StaffAccount(full_name=username.title(), email=f"{username}@gym.com", username=username,
                           job_title=job_title, role=role, branch=branch)
    account.set_password(PASSWORD)
    account.save()
    return account


def _coach(username, branch="Hamra"):
    return _staff(username, [], branch=branch, job_title=StaffAccount.JobTitle.COACH)


def _member(name, username, branch="Hamra", days_valid=60):
    today = timezone.localdate()
    member = Member(name=name, email=f"{username}@example.com", phone="70000000", branch=branch, join_date=today,
                    username=username, subscription_expires_at=today + timedelta(days=days_valid))
    member.set_password(PASSWORD)
    member.save()
    return member


def _member_login(client, username):
    res = client.post("/api/members/login", {"username": username, "password": PASSWORD}, content_type="application/json")
    assert res.status_code == 200, res.content


def _class_type(name="Yoga", branch="Hamra"):
    return ClassType.objects.create(branch=branch, name=name, max_capacity=10, default_duration_minutes=60)


def _finished_class(coach, branch="Hamra"):
    starts_at = local_datetime(timezone.localdate() - timedelta(days=1), rules.time(18, 0))
    return GymClass.objects.create(
        name="Yoga", class_type=_class_type(branch=branch), coach=coach, branch=branch,
        capacity=10, starts_at=starts_at, ends_at=starts_at + timedelta(hours=1),
    )


def _finished_pt_session(coach, member, branch="Hamra"):
    starts_at = local_datetime(timezone.localdate() - timedelta(days=1), rules.time(9, 0))
    return PTSession.objects.create(
        coach=coach, member=member, branch=branch, starts_at=starts_at, ends_at=starts_at + timedelta(hours=1),
    )


def _checked_in(member, branch, at):
    visit = CheckIn.objects.create(member=member, branch=branch, result=CheckIn.Result.ALLOWED)
    CheckIn.objects.filter(id=visit.id).update(checked_in_at=at)
    return visit


class AttendancePointsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hadi = _coach("hadi")
        cls.lea = _member("Lea Haddad", "lea")
        cls.sami = _member("Sami Khoury", "sami")

    def test_attending_a_class_earns_points(self):
        gym_class = _finished_class(self.hadi)
        booking = ClassBooking.objects.create(member=self.lea, gym_class=gym_class)
        _checked_in(self.lea, "Hamra", gym_class.starts_at - timedelta(minutes=5))

        rules.settle_attendance(now=gym_class.ends_at + timedelta(minutes=5))

        booking.refresh_from_db()
        self.assertEqual(booking.attendance, "Attended")
        entry = LoyaltyPointEntry.objects.get()
        self.assertEqual((entry.member, entry.points, entry.reason, entry.class_booking), (self.lea, 10, "ClassAttended", booking))
        self.assertEqual(points.balance(self.lea), 10)

    def test_a_no_show_earns_no_points(self):
        gym_class = _finished_class(self.hadi)
        ClassBooking.objects.create(member=self.sami, gym_class=gym_class)  # never checked in

        rules.settle_attendance(now=gym_class.ends_at + timedelta(minutes=5))

        self.assertFalse(LoyaltyPointEntry.objects.exists())
        self.assertEqual(points.balance(self.sami), 0)

    def test_settling_the_same_booking_twice_only_pays_out_once(self):
        gym_class = _finished_class(self.hadi)
        booking = ClassBooking.objects.create(member=self.lea, gym_class=gym_class)
        _checked_in(self.lea, "Hamra", gym_class.starts_at - timedelta(minutes=5))
        rules.settle_attendance(now=gym_class.ends_at + timedelta(minutes=5))

        # Calling the awarding function again directly (e.g. two requests
        # racing to settle at once) must not pay out a second time - the
        # model's unique constraint on class_booking backs get_or_create.
        points.award_class_attendance(booking)

        self.assertEqual(LoyaltyPointEntry.objects.filter(class_booking=booking).count(), 1)
        self.assertEqual(points.balance(self.lea), 10)

    def test_attending_a_private_training_session_earns_points(self):
        session = _finished_pt_session(self.hadi, self.lea)
        _checked_in(self.lea, "Hamra", session.starts_at - timedelta(minutes=5))

        rules.settle_attendance(now=session.ends_at + timedelta(minutes=5))

        session.refresh_from_db()
        self.assertEqual(session.attendance, "Attended")
        entry = LoyaltyPointEntry.objects.get()
        self.assertEqual((entry.member, entry.points, entry.reason, entry.pt_session), (self.lea, 10, "PTAttended", session))
        self.assertEqual(points.balance(self.lea), 10)

    def test_a_missed_pt_session_earns_no_points(self):
        session = _finished_pt_session(self.hadi, self.sami)  # never checked in

        rules.settle_attendance(now=session.ends_at + timedelta(minutes=5))

        self.assertFalse(LoyaltyPointEntry.objects.exists())


class ReferralPointsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MembershipPlan.objects.create(name="Basic", price="25.00")
        cls.desk = _staff("desk", ["manage_members"])
        cls.lea = _member("Lea Haddad", "lea")  # the referrer

    def _walk_in(self, referral_code="", **extra):
        body = {
            "name": "Tina Nassar", "email": "tina@example.com", "phone": "71111111", "branch": "Hamra",
            "membershipPlan": "Basic", "paymentMethod": "Cash", "paymentDuration": "1 Month",
            "liabilityWaiverAccepted": True, "healthDisclaimerAccepted": True, "signatureName": "Tina Nassar",
            "referralCode": referral_code, **extra,
        }
        return self.client.post("/api/members", body, content_type="application/json")

    def _signup(self, referral_code="", **extra):
        body = {
            "name": "Tina Nassar", "email": "tina@example.com", "phone": "71111111", "branch": "Hamra",
            "membershipPlan": "Basic", "username": "tina", "password": "Password123!",
            "paymentMethod": "Cash", "paymentDuration": "1 Month",
            "liabilityWaiverAccepted": True, "healthDisclaimerAccepted": True, "signatureName": "Tina Nassar",
            "referralCode": referral_code, **extra,
        }
        return self.client.post("/api/members/signup", body, content_type="application/json")

    def test_every_new_member_gets_a_unique_referral_code(self):
        self.assertTrue(self.lea.referral_code)
        other = _member("Omar Haddad", "omar")
        self.assertNotEqual(self.lea.referral_code, other.referral_code)

    def test_a_walk_in_registration_with_a_referral_code_credits_the_referrer(self):
        staff_login(self.client, "desk", PASSWORD)
        res = self._walk_in(referral_code=self.lea.referral_code.lower())  # case-insensitive
        self.assertEqual(res.status_code, 201, res.content)

        new_member = Member.objects.get(email="tina@example.com")
        entry = LoyaltyPointEntry.objects.get()
        self.assertEqual((entry.member, entry.points, entry.reason, entry.referred_member), (self.lea, 50, "Referral", new_member))
        self.assertEqual(points.balance(self.lea), 50)

        entry_log = AuditLog.objects.get(action=AuditLog.Action.MEMBER_REGISTERED)
        self.assertEqual(entry_log.details["referredBy"], "Lea Haddad")
        self.assertIn("referred by Lea Haddad", entry_log.summary)

    def test_an_online_signup_with_a_referral_code_credits_the_referrer(self):
        res = self._signup(referral_code=self.lea.referral_code)
        self.assertEqual(res.status_code, 201, res.content)

        new_member = Member.objects.get(username="tina")
        entry = LoyaltyPointEntry.objects.get()
        self.assertEqual((entry.member, entry.reason, entry.referred_member), (self.lea, "Referral", new_member))

        entry_log = AuditLog.objects.get(action=AuditLog.Action.MEMBER_SIGNED_UP)
        self.assertEqual(entry_log.details["referredBy"], "Lea Haddad")

    def test_registering_without_a_referral_code_credits_nobody(self):
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self._walk_in().status_code, 201)
        self.assertFalse(LoyaltyPointEntry.objects.exists())

    def test_an_unknown_referral_code_is_refused(self):
        staff_login(self.client, "desk", PASSWORD)
        res = self._walk_in(referral_code="NOPE12")
        self.assertEqual(res.status_code, 400)
        self.assertIn("NOPE12", res.json()["error"]["referralCode"][0])
        self.assertFalse(Member.objects.filter(email="tina@example.com").exists())

    def test_two_friends_can_use_the_same_referral_code(self):
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self._walk_in(referral_code=self.lea.referral_code).status_code, 201)
        self.assertEqual(
            self._walk_in(referral_code=self.lea.referral_code, email="rita@example.com", phone="71222222",
                          signatureName="Rita Fares", name="Rita Fares").status_code,
            201,
        )
        self.assertEqual(points.balance(self.lea), 100)
        self.assertEqual(LoyaltyPointEntry.objects.filter(member=self.lea, reason="Referral").count(), 2)


class MyLoyaltyViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lea = _member("Lea Haddad", "lea")

    def test_not_authenticated(self):
        self.assertEqual(self.client.get("/api/members/me/loyalty").status_code, 401)

    def test_shows_balance_referral_code_and_entries(self):
        hadi = _coach("hadi")
        gym_class = _finished_class(hadi)
        booking = ClassBooking.objects.create(member=self.lea, gym_class=gym_class)
        _checked_in(self.lea, "Hamra", gym_class.starts_at - timedelta(minutes=5))
        rules.settle_attendance(now=gym_class.ends_at + timedelta(minutes=5))
        points.award_referral(self.lea, _member("Tina Nassar", "tina"))

        _member_login(self.client, "lea")
        res = self.client.get("/api/members/me/loyalty")
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["balance"], 60)
        self.assertEqual(body["referralCode"], self.lea.referral_code)
        self.assertEqual({e["reason"] for e in body["entries"]}, {"ClassAttended", "Referral"})
        self.assertEqual(len(body["entries"]), 2)
