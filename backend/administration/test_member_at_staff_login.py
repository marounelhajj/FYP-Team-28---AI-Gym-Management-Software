from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from members.models import Member

PASSWORD = "ChangeMe123!"


# A gym member who types their own login into the staff sign-in is told it's a
# member account (so the app signs them in on the member side) - but only with
# the right password, so the staff form can't be used to discover usernames.
class MemberAtStaffLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        member = Member(name="Lea Haddad", email="lea@example.com", phone="1", branch="Hamra",
                        join_date=timezone.localdate(), username="lea",
                        subscription_expires_at=timezone.localdate() + timedelta(days=30))
        member.set_password(PASSWORD)
        member.save()

    def staff_login(self, username, password):
        return self.client.post("/api/auth/login", {"username": username, "password": password},
                                content_type="application/json")

    def test_a_members_own_login_is_recognised(self):
        res = self.staff_login("lea", PASSWORD)
        self.assertEqual(res.status_code, 401)
        self.assertTrue(res.json()["memberAccount"])
        self.assertNotIn("staff_account_id", self.client.session)

    def test_a_wrong_password_looks_like_any_unknown_username(self):
        for username in ("lea", "nobody"):
            res = self.staff_login(username, "wrong")
            self.assertEqual(res.json(), {"error": "Invalid username or password."})
