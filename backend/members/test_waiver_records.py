from unittest import mock

from django.test import TestCase
from django.utils import timezone

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from plans.models import MembershipPlan

from .models import Member, Waiver, WaiverSignature
from .privacy import anonymize_member
from .waiver import WAIVER_VERSION, current_text

# SCRUM-83: "One record is stored per signature: member id, waiver version,
# signed name, timestamp, IP address, and a snapshot of the exact text
# version signed. Waiver text is versioned, so a new version can require
# re-signing. Staff (receptionist, general manager) can see whether a member
# has a signed waiver and open the signed record. Members see only their
# own. Tests cover ... permission checks on viewing records."

PASSWORD = "ChangeMe123!"
SIGNED = {"liabilityWaiverAccepted": True, "healthDisclaimerAccepted": True}


def staff(username, permissions):
    role = Role.objects.create(name=f"{username} role", permissions=permissions)
    account = StaffAccount(
        full_name=username.title(), email=f"{username}@gym.com", username=username,
        job_title=StaffAccount.JobTitle.RECEPTIONIST, role=role,
    )
    account.set_password(PASSWORD)
    account.save()
    return account


class WaiverRecordTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MembershipPlan.objects.create(name="Basic", price="35.00")
        cls.desk = staff("desk", ["manage_members"])
        staff("coachy", ["view_coach_ratings"])

    def signup(self, name="Lea Haddad", username="lea", ip="203.0.113.7"):
        payload = {
            "name": name, "email": f"{username}@example.com", "phone": "70123456", "branch": "Hamra",
            "membershipPlan": "Basic", "username": username, "password": "Password123!",
            "paymentMethod": "Card", "paymentDuration": "1 Month", **SIGNED, "signatureName": name,
        }
        res = self.client.post("/api/members/signup", payload, content_type="application/json", REMOTE_ADDR=ip)
        self.assertEqual(res.status_code, 201, res.content)
        return Member.objects.get(username=username)

    def test_signature_stores_version_time_ip_and_exact_text(self):
        before = timezone.now()
        member = self.signup()
        signature = WaiverSignature.objects.get(member=member)
        self.assertEqual(signature.waiver_version, WAIVER_VERSION)
        self.assertEqual(signature.signature_name, "Lea Haddad")
        self.assertEqual(signature.ip_address, "203.0.113.7")
        self.assertEqual(signature.text_snapshot, current_text())
        self.assertIn("assume all such risks", signature.text_snapshot)
        self.assertGreaterEqual(signature.signed_at, before)
        self.assertEqual(member.waiver.ip_address, "203.0.113.7")
        self.assertEqual(member.waiver.text_snapshot, current_text())

    def test_walk_in_records_the_desk_ip_and_witness(self):
        staff_login(self.client, "desk", PASSWORD)
        payload = {
            "name": "Sami Khoury", "email": "sami@example.com", "phone": "71000000", "branch": "Jnah",
            "membershipPlan": "Basic", "paymentMethod": "Cash", "paymentDuration": "1 Month",
            **SIGNED, "signatureName": "Sami Khoury",
        }
        res = self.client.post("/api/members", payload, content_type="application/json", REMOTE_ADDR="10.0.0.5")
        self.assertEqual(res.status_code, 201, res.content)
        signature = WaiverSignature.objects.get(member__name="Sami Khoury")
        self.assertEqual(signature.ip_address, "10.0.0.5")
        self.assertEqual(signature.witnessed_by, self.desk)
        self.assertEqual(signature.signed_via, Waiver.SignedVia.FRONT_DESK)

    # --- staff open the signed record ---
    def test_staff_open_the_signed_record_and_it_is_audited(self):
        member = self.signup()
        self.client.logout()
        staff_login(self.client, "desk", PASSWORD)
        res = self.client.get(f"/api/members/{member.pk}/waiver")
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertTrue(data["onFile"])
        self.assertFalse(data["needsResign"])
        self.assertEqual(data["current"]["ipAddress"], "203.0.113.7")
        self.assertEqual(data["current"]["text"], current_text())
        self.assertEqual(len(data["history"]), 1)
        entry = AuditLog.objects.get(action=AuditLog.Action.WAIVER_VIEWED)
        self.assertEqual(entry.target_id, str(member.pk))
        # The member directory/detail shows whether it's on file and current.
        detail = self.client.get(f"/api/members/{member.pk}").json()
        self.assertFalse(detail["waiver"]["needsResign"])

    def test_viewing_records_needs_manage_members(self):
        member = self.signup()
        self.client.logout()
        self.assertEqual(self.client.get(f"/api/members/{member.pk}/waiver").status_code, 401)
        staff_login(self.client, "coachy", PASSWORD)
        self.assertEqual(self.client.get(f"/api/members/{member.pk}/waiver").status_code, 403)
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.WAIVER_VIEWED).exists())

    def test_members_only_see_their_own(self):
        lea = self.signup()
        self.client.logout()
        omar = self.signup(name="Omar Saab", username="omar", ip="198.51.100.2")
        # Omar is signed in now: his own record, never Lea's.
        mine = self.client.get("/api/members/me/waiver")
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(mine.json()["memberId"], omar.pk)
        self.assertEqual(mine.json()["current"]["signatureName"], "Omar Saab")
        # The staff endpoint doesn't accept a member session.
        self.assertEqual(self.client.get(f"/api/members/{lea.pk}/waiver").status_code, 401)
        self.client.logout()
        self.assertEqual(self.client.get("/api/members/me/waiver").status_code, 401)

    # --- a new version requires re-signing ---
    def test_new_version_requires_resigning(self):
        member = self.signup()
        res = self.client.post("/api/members/me/waiver", {**SIGNED, "signatureName": "Lea Haddad"},
                               content_type="application/json")
        self.assertEqual(res.status_code, 400)  # already up to date

        with mock.patch("members.waiver.WAIVER_VERSION", "2027-01"):
            data = self.client.get("/api/members/me/waiver").json()
            self.assertTrue(data["needsResign"])
            self.assertEqual(data["currentVersion"], "2027-01")
            self.assertTrue(self.client.get("/api/members/me").json()["waiver"]["needsResign"])

            res = self.client.post("/api/members/me/waiver", {**SIGNED, "signatureName": "Someone Else"},
                                   content_type="application/json")
            self.assertEqual(res.status_code, 400)
            res = self.client.post("/api/members/me/waiver", {"liabilityWaiverAccepted": True,
                                   "healthDisclaimerAccepted": False, "signatureName": "Lea Haddad"},
                                   content_type="application/json")
            self.assertEqual(res.status_code, 400)

            res = self.client.post("/api/members/me/waiver", {**SIGNED, "signatureName": "lea  haddad"},
                                   content_type="application/json", REMOTE_ADDR="192.0.2.9")
            self.assertEqual(res.status_code, 200, res.content)
            data = res.json()
            self.assertFalse(data["needsResign"])
            self.assertEqual(data["current"]["waiverVersion"], "2027-01")
            self.assertEqual(data["current"]["ipAddress"], "192.0.2.9")
            self.assertEqual(len(data["history"]), 2)
        versions = list(WaiverSignature.objects.filter(member=member).values_list("waiver_version", flat=True))
        self.assertEqual(sorted(versions), sorted([WAIVER_VERSION, "2027-01"]))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.WAIVER_SIGNED).exists())

    # --- privacy (SCRUM-62) ---
    def test_deletion_keeps_the_record_but_removes_name_and_ip(self):
        member = self.signup()
        anonymize_member(member)
        signature = WaiverSignature.objects.get(member=member)
        self.assertEqual(signature.signature_name, "[removed]")
        self.assertIsNone(signature.ip_address)
        self.assertEqual(signature.waiver_version, WAIVER_VERSION)
        member.waiver.refresh_from_db()
        self.assertIsNone(member.waiver.ip_address)

    def test_export_includes_every_signature(self):
        self.signup()
        res = self.client.get("/api/members/me/export")
        self.assertEqual(res.status_code, 200)
        body = res.json() if res.get("Content-Type", "").startswith("application/json") else None
        if body is None:
            import json
            body = json.loads(b"".join(res.streaming_content) if res.streaming else res.content)
        self.assertEqual(body["waiver"]["ipAddress"], "203.0.113.7")
        self.assertEqual(len(body["waiverSignatures"]), 1)
        self.assertEqual(body["waiverSignatures"][0]["text"], current_text())
