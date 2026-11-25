from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from administration.testing import staff_login

from .models import Segment
from .testing import PASSWORD, attended_class, branch_manager, marketing, member, pt_session, purchase

# User story (SCRUM-113): "As a marketing staff member, I want to view class
# and service uptake per segment, so that I can see which offerings each
# group actually uses."


class UptakeTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        # Ten Hamra members. Four Premium ones do Yoga (twice each) and two of them have a PT.
        self.premium = []
        for i in range(4):
            m = member(f"Pia Premium{i}", branch="Hamra")
            m.membership_plan = "Premium"
            m.save()
            attended_class(m, "Yoga", 3 + i)
            attended_class(m, "Yoga", 10 + i)
            self.premium.append(m)
        pt_session(self.premium[0], 4, coach_username="pt0")
        pt_session(self.premium[1], 4, coach_username="pt1")
        self.basic = [member(f"Ben Basic{i}", branch="Hamra") for i in range(6)]
        attended_class(self.basic[0], "Spin", 5)
        purchase(self.basic[0], "Drinks", 2, quantity=3)
        purchase(self.basic[1], "Drinks", 2)
        # Outside the range: a Spin class 60 days ago.
        attended_class(self.basic[2], "Spin", 60)
        self.premium_seg = Segment.objects.create(name="Premium", filters={"plans": ["Premium"]})
        self.basic_seg = Segment.objects.create(name="Basic", filters={"plans": ["Basic"]})
        marketing()
        staff_login(self.client, "nadine", PASSWORD)

    def get(self, **params):
        res = self.client.get("/api/segments/uptake", params)
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def test_uptake_per_offering_and_segment(self):
        data = self.get(segments=f"{self.premium_seg.pk},{self.basic_seg.pk}")
        self.assertEqual(
            [(o["name"], o["kind"]) for o in data["offerings"]],
            [("Spin", "class"), ("Yoga", "class"), ("Personal training", "pt"), ("Shop: Drinks", "shop")],
        )
        everyone, premium, basic = data["series"]
        self.assertEqual((everyone["name"], everyone["size"]), ("All members", 10))
        self.assertEqual(everyone["cells"]["Yoga"], {"users": 4, "uptakePct": 40.0, "usesPerMember": 0.8, "highlight": None})
        self.assertEqual(premium["cells"]["Yoga"]["uptakePct"], 100.0)
        self.assertEqual(premium["cells"]["Yoga"]["usesPerMember"], 2.0)
        self.assertEqual(premium["cells"]["Personal training"]["uptakePct"], 50.0)
        self.assertEqual(basic["cells"]["Shop: Drinks"]["users"], 2)
        self.assertEqual(basic["cells"]["Shop: Drinks"]["usesPerMember"], round(4 / 6, 2))
        self.assertEqual(basic["cells"]["Spin"]["users"], 1)  # the one 60 days ago is outside the range

    def test_highlights_well_above_and_below_average(self):
        data = self.get(segments=f"{self.premium_seg.pk},{self.basic_seg.pk}")
        _, premium, basic = data["series"]
        self.assertEqual(premium["cells"]["Yoga"]["highlight"], "above")
        self.assertEqual(basic["cells"]["Yoga"]["highlight"], "below")
        self.assertEqual(premium["cells"]["Personal training"]["highlight"], "above")
        # Spin: 10% overall vs 16.7% for Basic - not 10 points apart.
        self.assertIsNone(basic["cells"]["Spin"]["highlight"])

    def test_date_range(self):
        start = (self.today - timedelta(days=70)).isoformat()
        end = (self.today - timedelta(days=50)).isoformat()
        data = self.get(**{"from": start, "to": end})
        self.assertEqual([o["name"] for o in data["offerings"]], ["Spin"])
        self.assertEqual(data["from"], start)
        self.assertEqual(data["to"], end)

    def test_default_range_is_last_30_days(self):
        data = self.get()
        self.assertEqual(data["to"], self.today.isoformat())
        self.assertEqual(data["from"], (self.today - timedelta(days=29)).isoformat())

    def test_bad_ranges(self):
        for params in ({"from": "nope"}, {"from": "2026-05-02", "to": "2026-05-01"},
                       {"from": "2024-01-01", "to": "2026-01-01"}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/api/segments/uptake", params).status_code, 400)

    def test_branch_filter_and_branch_manager_scope(self):
        other = member("Jo Jnah", branch="Jnah")
        attended_class(other, "Boxing", 2)
        self.assertIn("Boxing", [o["name"] for o in self.get()["offerings"]])
        self.assertNotIn("Boxing", [o["name"] for o in self.get(branch="Hamra")["offerings"]])
        branch_manager()
        self.client.logout()
        staff_login(self.client, "hamrabm", PASSWORD)
        self.assertNotIn("Boxing", [o["name"] for o in self.get()["offerings"]])
        self.assertEqual(self.client.get("/api/segments/uptake", {"branch": "Jnah"}).status_code, 403)
