from datetime import date, timedelta

from django.test import TestCase

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from members import qr
from members.models import Member

from .models import CheckInFlag

PASSWORD = "ChangeMe123!"


# User story (SCRUM-33): "As a receptionist, I want to check in members via
# QR code or membership ID, so that I can quickly verify membership status
# and control entry."
class QrCheckInTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        role = Role.objects.create(name="Receptionist", permissions=["manage_members"])
        desk = StaffAccount(
            full_name="Desk", email="desk@gym.com", username="desk",
            job_title=StaffAccount.JobTitle.RECEPTIONIST, role=role,
        )
        desk.set_password(PASSWORD)
        desk.save()
        cls.lea = Member(
            name="Lea Haddad", email="lea@example.com", phone="1", branch="Hamra",
            join_date=date.today(), username="lea",
            subscription_expires_at=date.today() + timedelta(days=30),
        )
        cls.lea.set_password(PASSWORD)
        cls.lea.save()
        cls.other = Member.objects.create(
            name="Sami Khoury", email="sami@example.com", phone="2", branch="Jnah",
            join_date=date.today(), subscription_expires_at=date.today() + timedelta(days=30),
        )

    def setUp(self):
        staff_login(self.client, "desk", PASSWORD)

    def post(self, path, body):
        return self.client.post(path, body, content_type="application/json")

    def test_check_in_and_out_with_qr_code(self):
        payload = qr.payload_for(self.lea)
        res = self.post("/api/checkins", {"qrCode": payload})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["member"]["name"], "Lea Haddad")
        self.assertEqual(res.json()["checkIn"]["result"], "Allowed")

        res = self.post("/api/checkins/checkout", {"qrCode": payload})
        self.assertEqual(res.status_code, 200, res.content)

    def test_membership_id_still_works(self):
        res = self.post("/api/checkins", {"membershipId": self.lea.id})
        self.assertEqual(res.status_code, 201)

    def test_forged_or_edited_codes_are_refused(self):
        genuine = qr.payload_for(self.lea)
        edited = genuine.replace(f":{self.lea.id}:", f":{self.other.id}:")
        for code in [f"FFM1:{self.other.id}", edited, "hello", genuine + "x"]:
            res = self.post("/api/checkins", {"qrCode": code})
            self.assertEqual(res.status_code, 400, code)
            self.assertIn("qrCode", res.json()["error"])

    def test_needs_an_id_or_a_code(self):
        res = self.post("/api/checkins", {})
        self.assertEqual(res.status_code, 400)
        self.assertIn("membershipId", res.json()["error"])

    def test_member_gets_their_own_qr_code(self):
        self.client.post("/api/auth/logout")
        self.post("/api/members/login", {"username": "lea", "password": PASSWORD})
        res = self.client.get("/api/members/me/qr")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["membershipId"], self.lea.id)
        self.assertEqual(qr.member_id_from(res.json()["payload"]), self.lea.id)
        self.assertTrue(res.json()["qrCode"].startswith("data:image/svg+xml"))

    def test_qr_endpoint_needs_a_member_session(self):
        self.assertEqual(self.client.get("/api/members/me/qr").status_code, 401)


# User story: "As a receptionist, I want to flag a suspicious or duplicate
# check in attempt, so that I can prevent membership sharing or fraudulent access."
class CheckInFlagTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for username, name, permissions in (("desk", "Dana Desk", ["manage_members"]),
                                            ("mkt", "Mark Eting", ["manage_marketing_campaigns"])):
            role = Role.objects.create(name=f"{username} role", permissions=permissions)
            account = StaffAccount(full_name=name, email=f"{username}@gym.com", username=username,
                                   job_title=StaffAccount.JobTitle.RECEPTIONIST, role=role)
            account.set_password(PASSWORD)
            account.save()
        cls.lea = Member.objects.create(
            name="Lea Haddad", email="lea@example.com", phone="1", branch="Hamra",
            join_date=date.today(), subscription_expires_at=date.today() + timedelta(days=30),
        )

    def setUp(self):
        staff_login(self.client, "desk", PASSWORD)

    def post(self, path, body=None):
        return self.client.post(path, body or {}, content_type="application/json")

    def check_in(self):
        return self.post("/api/checkins", {"membershipId": self.lea.id}).json()

    def check_out(self):
        return self.post("/api/checkins/checkout", {"membershipId": self.lea.id})

    def duplicate_attempt(self):
        self.check_in()
        return self.check_in()["checkIn"]

    def flag(self, check_in_id, **body):
        return self.post(f"/api/checkins/{check_in_id}/flag", {"reason": "Duplicate check-in", **body})

    def resolve(self, flag_id, outcome, note=""):
        return self.post(f"/api/checkins/flags/{flag_id}/resolve", {"outcome": outcome, "note": note})

    def test_duplicate_attempt_is_highlighted_for_review(self):
        duplicate = self.duplicate_attempt()
        self.assertEqual(duplicate["reason"], "Already checked in")
        self.assertIn("sharing", duplicate["suspicion"])
        recent = self.client.get("/api/checkins").json()["results"]
        allowed = next(c for c in recent if c["result"] == "Allowed")
        self.assertIsNone(allowed["suspicion"])

    def test_flagging_records_who_and_why_and_writes_the_audit_log(self):
        duplicate = self.duplicate_attempt()
        res = self.flag(duplicate["id"], note="  Different person   than the photo ")
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertEqual((body["status"], body["flaggedBy"], body["note"]),
                         ("Open", "Dana Desk", "Different person than the photo"))
        self.assertEqual(body["checkIn"]["id"], duplicate["id"])

        row = next(c for c in self.client.get("/api/checkins").json()["results"] if c["id"] == duplicate["id"])
        self.assertEqual(row["flag"]["reason"], "Duplicate check-in")

        entry = AuditLog.objects.get(action=AuditLog.Action.CHECKIN_FLAGGED)
        self.assertEqual((entry.actor_username, entry.target_label, entry.branch), ("desk", "Lea Haddad", "Hamra"))

    def test_an_attempt_can_only_be_flagged_once(self):
        duplicate = self.duplicate_attempt()
        self.assertEqual(self.flag(duplicate["id"]).status_code, 201)
        self.assertEqual(self.flag(duplicate["id"], reason="Membership sharing").status_code, 400)
        self.assertEqual(CheckInFlag.objects.count(), 1)

    def test_reason_is_required_and_other_needs_a_note(self):
        attempt = self.check_in()["checkIn"]
        self.assertIn("reason", self.flag(attempt["id"], reason="Weird vibes").json()["error"])
        self.assertIn("note", self.flag(attempt["id"], reason="Other", note="  ").json()["error"])
        self.assertEqual(self.flag(attempt["id"], reason="Other", note="Tailgated in").status_code, 201)

    def test_flagged_member_triggers_a_photo_id_warning_at_check_in(self):
        self.assertIsNone(self.check_in()["flagWarning"])
        self.check_out()
        allowed = self.check_in()["checkIn"]
        self.flag(allowed["id"], reason="Membership sharing")
        self.check_out()

        warning = self.check_in()["flagWarning"]
        self.assertEqual((warning["count"], warning["confirmed"], warning["latestReason"]),
                         (1, 0, "Membership sharing"))

    def test_confirmed_keeps_warning_and_dismissed_stops(self):
        flag_id = self.flag(self.duplicate_attempt()["id"]).json()["id"]
        res = self.resolve(flag_id, "Confirmed", "Brother used it")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.json()["status"], res.json()["resolvedBy"]), ("Confirmed", "Dana Desk"))
        self.assertEqual(self.check_in()["flagWarning"]["confirmed"], 1)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CHECKIN_FLAG_RESOLVED).exists())

        CheckInFlag.objects.all().delete()
        other_id = self.flag(self.check_in()["checkIn"]["id"]).json()["id"]
        self.resolve(other_id, "Dismissed")
        self.assertIsNone(self.check_in()["flagWarning"])

    def test_a_flag_is_resolved_only_once_with_a_valid_outcome(self):
        flag_id = self.flag(self.duplicate_attempt()["id"]).json()["id"]
        self.assertIn("outcome", self.resolve(flag_id, "Open").json()["error"])
        self.resolve(flag_id, "Dismissed")
        self.assertEqual(self.resolve(flag_id, "Confirmed").status_code, 400)
        self.assertEqual(CheckInFlag.objects.get(id=flag_id).status, "Dismissed")

    def test_flag_list_filters_by_status(self):
        open_flag = self.flag(self.duplicate_attempt()["id"]).json()["id"]
        closed_flag = self.flag(self.check_in()["checkIn"]["id"]).json()["id"]
        self.resolve(closed_flag, "Dismissed")

        default = self.client.get("/api/checkins/flags").json()
        self.assertEqual(([f["id"] for f in default["results"]], default["openCount"]), ([open_flag], 1))
        self.assertEqual(default["results"][0]["checkIn"]["memberName"], "Lea Haddad")
        dismissed = self.client.get("/api/checkins/flags?status=Dismissed").json()["results"]
        self.assertEqual([f["id"] for f in dismissed], [closed_flag])
        self.assertEqual(len(self.client.get("/api/checkins/flags?status=all").json()["results"]), 2)
        self.assertEqual(self.client.get("/api/checkins/flags?status=Bogus").status_code, 400)

    def test_needs_manage_members(self):
        attempt = self.check_in()["checkIn"]
        flag_id = self.flag(attempt["id"]).json()["id"]
        calls = [
            ("post", f"/api/checkins/{attempt['id']}/flag"),
            ("get", "/api/checkins/flags"),
            ("post", f"/api/checkins/flags/{flag_id}/resolve"),
        ]
        self.client.post("/api/auth/logout")
        for verb, url in calls:
            self.assertEqual(getattr(self.client, verb)(url).status_code, 401, url)
        staff_login(self.client, "mkt", PASSWORD)
        for verb, url in calls:
            self.assertEqual(getattr(self.client, verb)(url).status_code, 403, url)

    def test_unknown_attempt_or_flag(self):
        self.assertEqual(self.flag(9999).status_code, 404)
        self.assertEqual(self.resolve(9999, "Dismissed").status_code, 404)
