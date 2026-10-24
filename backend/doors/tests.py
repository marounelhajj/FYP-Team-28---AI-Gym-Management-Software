from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from administration.models import Role, StaffAccount
from administration.testing import staff_login
from audit.models import AuditLog
from checkins.models import CheckIn, CheckInFlag
from members import qr
from members.models import Member
from plans.models import MembershipPlan

from .models import Door

PASSWORD = "ChangeMe123!"


def _staff(username, permissions):
    role = Role.objects.create(name=f"{username} role", permissions=permissions)
    account = StaffAccount(full_name=username.title(), email=f"{username}@gym.com", username=username,
                           job_title=StaffAccount.JobTitle.RECEPTIONIST, role=role)
    account.set_password(PASSWORD)
    account.save()


# User story: "As a receptionist, I want door access to be granted or revoked
# automatically based on membership status, so that entry control stays in
# sync with payments without manual card management."
class DoorAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        MembershipPlan.objects.create(name="Basic", price="25.00")
        _staff("desk", ["manage_members"])
        _staff("admin", ["manage_doors"])
        cls.today = timezone.localdate()

    def setUp(self):
        self.entrance, self.entrance_key = self.make_door(Door.Kind.ENTRANCE)
        self.exit, self.exit_key = self.make_door(Door.Kind.EXIT)

    def make_door(self, kind, branch="Hamra"):
        door = Door(name=f"{kind} door", branch=branch, kind=kind)
        key = door.set_new_key()
        door.save()
        return door, key

    def member(self, name="Lea Haddad", expires_in_days=30, status="Active", username=None):
        member = Member(
            name=name, email=f"{name.split()[0].lower()}@example.com", phone="1", branch="Jnah",
            join_date=self.today, status=status, username=username,
            subscription_expires_at=None if expires_in_days is None else self.today + timedelta(days=expires_in_days),
        )
        member.set_password(PASSWORD)
        member.save()
        return member

    def scan(self, code, key=None):
        return self.client.post("/api/doors/scan", {"qrCode": code}, content_type="application/json",
                                headers={"X-Door-Key": key or self.entrance_key})

    def enter(self, member):
        return self.scan(qr.payload_for(Member.objects.get(id=member.id))).json()

    def leave(self, member):
        return self.scan(qr.payload_for(Member.objects.get(id=member.id)), key=self.exit_key).json()

    def post(self, path, body=None):
        return self.client.post(path, body or {}, content_type="application/json")

    # --- the access rule ---
    def test_paid_member_is_let_in_and_the_visit_is_recorded(self):
        lea = self.member()
        res = self.enter(lea)
        self.assertTrue(res["granted"], res)
        self.assertEqual(res["member"], {"id": lea.id, "firstName": "Lea"})
        self.assertIn("Open until", res["message"])
        visit = CheckIn.objects.get(member=lea)
        self.assertEqual((visit.result, visit.door, visit.branch), ("Allowed", self.entrance, "Hamra"))

    def test_valid_through_the_last_day_and_refused_the_day_after(self):
        self.assertTrue(self.enter(self.member("Last Day", expires_in_days=0))["granted"])
        lapsed = self.member("Sami Khoury", expires_in_days=-1)
        res = self.enter(lapsed)
        self.assertFalse(res["granted"])
        self.assertIn("expired", res["message"])
        self.assertEqual(CheckIn.objects.get(member=lapsed).reason, "Expired")
        self.assertEqual(Member.objects.get(id=lapsed.id).status, "Frozen")

    def test_a_payment_opens_the_door_on_the_very_next_scan(self):
        new = self.member("Nour Saad", expires_in_days=None)
        self.assertEqual(self.enter(new)["message"], "No paid subscription yet.")
        staff_login(self.client, "desk", PASSWORD)
        paid = self.post(f"/api/members/{new.id}/payments", {"membershipPlan": "Basic", "method": "Cash", "duration": "1 Month"})
        self.assertEqual(paid.status_code, 201, paid.content)
        self.assertTrue(self.enter(new)["granted"])

    def test_freezing_and_resuming_in_the_app_revoke_and_restore_access(self):
        lea = self.member(username="lea")
        self.post("/api/members/login", {"username": "lea", "password": PASSWORD})
        self.post("/api/members/me/freeze")
        res = self.enter(lea)
        self.assertFalse(res["granted"])
        self.assertIn("frozen", res["message"])
        self.post("/api/members/me/resume")
        self.assertTrue(self.enter(lea)["granted"])

    def test_cancelling_revokes_access(self):
        lea = self.member()
        staff_login(self.client, "desk", PASSWORD)
        self.post(f"/api/members/{lea.id}/cancel")
        self.assertEqual(self.enter(lea)["message"], "Membership cancelled.")

    def test_a_reissued_card_stops_the_old_code_at_the_door(self):
        lea = self.member()
        old_code = qr.payload_for(lea)
        staff_login(self.client, "desk", PASSWORD)
        self.post(f"/api/members/{lea.id}/access-card", {"reason": "Lost", "identityConfirmed": True})
        res = self.scan(old_code).json()
        self.assertFalse(res["granted"])
        self.assertIn("replaced", res["message"])
        self.assertTrue(self.enter(lea)["granted"])

    # --- edge cases ---
    def test_doors_only_accept_genuine_qr_codes(self):
        lea = self.member()
        forged = qr.payload_for(lea).replace(f":{lea.id}:", f":{lea.id + 1}:")
        for body in ({"membershipId": lea.id}, {"qrCode": str(lea.id)}, {"qrCode": forged}, {"qrCode": ""}):
            res = self.client.post("/api/doors/scan", body, content_type="application/json",
                                   headers={"X-Door-Key": self.entrance_key})
            self.assertEqual(res.status_code, 200)
            self.assertFalse(res.json()["granted"], body)
        self.assertFalse(CheckIn.objects.exists())

    def test_a_second_entry_while_inside_is_refused_and_marked_for_review(self):
        lea = self.member()
        self.enter(lea)
        res = self.enter(lea)
        self.assertFalse(res["granted"])
        refused = CheckIn.objects.filter(member=lea, result="Denied").get()
        self.assertEqual(refused.reason, "Already checked in")
        staff_login(self.client, "desk", PASSWORD)
        recent = next(c for c in self.client.get("/api/checkins").json()["results"] if c["id"] == refused.id)
        self.assertEqual(recent["door"], "Entrance door")
        self.assertIsNotNone(recent["suspicion"])

    def test_exits_always_open_even_after_access_was_revoked_inside(self):
        lea = self.member()
        self.enter(lea)
        staff_login(self.client, "desk", PASSWORD)
        self.post(f"/api/members/{lea.id}/cancel")
        res = self.leave(lea)
        self.assertTrue(res["granted"])
        self.assertIn("you were in for", res["message"])
        self.assertIsNotNone(CheckIn.objects.get(member=lea, result="Allowed").checked_out_at)
        # No visit to close: the exit still opens.
        self.assertTrue(self.leave(self.member("Sami Khoury"))["granted"])

    def test_a_forgotten_check_out_does_not_lock_the_member_out(self):
        lea = self.member()
        self.enter(lea)
        CheckIn.objects.filter(member=lea).update(checked_in_at=timezone.now() - timedelta(hours=5))
        self.assertTrue(self.enter(lea)["granted"])

    def test_flagged_members_are_sent_to_the_front_desk(self):
        lea = self.member()
        self.enter(lea)
        self.leave(lea)
        visit = CheckIn.objects.get(member=lea)
        staff_login(self.client, "desk", PASSWORD)
        flag_id = self.post(f"/api/checkins/{visit.id}/flag", {"reason": "Membership sharing"}).json()["id"]

        res = self.enter(lea)
        self.assertFalse(res["granted"])
        self.assertEqual(res["message"], "This card needs a staff check today.")
        self.assertEqual(CheckIn.objects.filter(member=lea, result="Denied").get().reason, "ID check required")
        self.assertTrue(self.client.get(f"/api/members/{lea.id}/billing").json()["doorDeskOnly"])
        self.assertTrue(self.client.get(f"/api/members/{lea.id}/access-card").json()["doorDeskOnly"])
        # The desk can still let them in, with the photo ID warning.
        desk = self.post("/api/checkins", {"membershipId": lea.id}).json()
        self.assertEqual((desk["checkIn"]["result"], desk["flagWarning"]["count"]), ("Allowed", 1))
        self.post("/api/checkins/checkout", {"membershipId": lea.id})

        self.post(f"/api/checkins/flags/{flag_id}/resolve", {"outcome": "Confirmed"})
        self.assertFalse(self.enter(lea)["granted"])
        CheckIn.objects.filter(member=lea, result="Denied").delete()
        CheckInFlag.objects.filter(id=flag_id).update(status="Dismissed")
        self.assertTrue(self.enter(lea)["granted"])
        self.assertFalse(self.client.get(f"/api/members/{lea.id}/billing").json()["doorDeskOnly"])

    def test_a_flagged_member_never_learns_it_from_their_own_account(self):
        lea = self.member(username="lea")
        self.post("/api/members/login", {"username": "lea", "password": PASSWORD})
        for url in ("/api/members/me", "/api/members/me/billing"):
            self.assertNotIn("doorDeskOnly", self.client.get(url).json(), url)

    def test_the_front_desk_uses_the_same_rule(self):
        lapsed = self.member("Sami Khoury", expires_in_days=-3)
        staff_login(self.client, "desk", PASSWORD)
        res = self.post("/api/checkins", {"membershipId": lapsed.id}).json()
        self.assertEqual((res["checkIn"]["reason"], res["access"]["granted"]), ("Expired", False))

    def test_receptionist_sees_each_members_door_access(self):
        lea, sami = self.member(), self.member("Sami Khoury", expires_in_days=-3)
        staff_login(self.client, "desk", PASSWORD)
        granted = self.client.get(f"/api/members/{lea.id}").json()["doorAccess"]
        self.assertEqual((granted["granted"], granted["validUntil"]), (True, str(self.today + timedelta(days=30))))
        refused = self.client.get(f"/api/members/{sami.id}").json()["doorAccess"]
        self.assertEqual((refused["granted"], refused["reason"]), (False, "Expired"))

    # --- door readers ---
    def test_door_key_is_required_and_a_disabled_or_replaced_key_stops_working(self):
        lea = self.member()
        code = qr.payload_for(lea)
        self.assertEqual(self.client.post("/api/doors/scan", {"qrCode": code}, content_type="application/json").status_code, 401)
        self.assertEqual(self.scan(code, key="door_wrong").status_code, 401)

        staff_login(self.client, "admin", PASSWORD)
        self.client.patch(f"/api/doors/{self.entrance.id}", {"isActive": False}, content_type="application/json")
        self.assertEqual(self.scan(code).status_code, 403)
        self.client.patch(f"/api/doors/{self.entrance.id}", {"isActive": True}, content_type="application/json")

        new_key = self.post(f"/api/doors/{self.entrance.id}/rotate-key").json()["key"]
        self.assertEqual(self.scan(code).status_code, 401)
        self.assertTrue(self.scan(code, key=new_key).json()["granted"])

    def test_door_reader_knows_which_door_it_is_and_reports_in(self):
        res = self.client.get("/api/doors/self", headers={"X-Door-Key": self.exit_key})
        self.assertEqual(res.json(), {"name": "Exit door", "branch": "Hamra", "kind": "Exit"})
        self.enter(self.member())
        self.assertIsNotNone(Door.objects.get(id=self.entrance.id).last_seen_at)

    def test_admin_adds_doors_and_sees_the_key_only_once(self):
        staff_login(self.client, "admin", PASSWORD)
        res = self.post("/api/doors", {"name": "  Zalka   main entrance ", "branch": "Zalka", "kind": "Entrance"})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertTrue(res.json()["key"].startswith("door_"))
        self.assertEqual(res.json()["door"]["name"], "Zalka main entrance")
        listed = self.client.get("/api/doors").json()["results"]
        self.assertTrue(all("key" not in d and "keyHash" not in d for d in listed))
        self.assertIn("kind", self.post("/api/doors", {"name": "X", "branch": "Zalka", "kind": "Window"}).json()["error"])

        self.post(f"/api/doors/{res.json()['door']['id']}/rotate-key")
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertTrue({AuditLog.Action.DOOR_CREATED, AuditLog.Action.DOOR_KEY_ROTATED} <= actions)

    def test_managing_doors_needs_manage_doors(self):
        calls = [("get", "/api/doors"), ("post", "/api/doors"), ("patch", f"/api/doors/{self.entrance.id}"),
                 ("post", f"/api/doors/{self.entrance.id}/rotate-key")]
        for verb, url in calls:
            self.assertEqual(getattr(self.client, verb)(url).status_code, 401, url)
        staff_login(self.client, "desk", PASSWORD)
        for verb, url in calls:
            self.assertEqual(getattr(self.client, verb)(url).status_code, 403, url)
