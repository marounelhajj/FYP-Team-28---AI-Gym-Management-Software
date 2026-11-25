from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from administration.testing import staff_login

from .models import Segment
from .testing import PASSWORD, attended_class, branch_manager, marketing, member, visits
from .trends import periods

# User story (SCRUM-112): "As a marketing staff member, I want to view
# attendance trends over time by branch and member segment, so that I can
# see where engagement is growing or falling."


def days_ago_in_week(today, weeks_back, *weekdays):
    """Days-ago numbers for the given weekdays (0=Mon) of the complete week `weeks_back` before this one."""
    monday = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks_back)
    return [(today - (monday + timedelta(days=d))).days for d in weekdays]


class PeriodTests(TestCase):
    def test_complete_weeks_and_months(self):
        today = date(2026, 11, 24)  # a Tuesday
        weeks = periods("week", today)
        self.assertEqual(len(weeks), 12)
        self.assertEqual(weeks[-1][:2], (date(2026, 11, 16), date(2026, 11, 22)))
        months = periods("month", today)
        self.assertEqual(len(months), 6)
        self.assertEqual(months[-1][:2], (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(months[0][:2], (date(2026, 5, 1), date(2026, 5, 31)))


class TrendTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        # Hamra: 1 regular whose visits grow (1 -> 3 a week), 1 who stopped.
        self.grower = member("Gina Grow", branch="Hamra")
        visits(self.grower, days_ago_in_week(self.today, 2, 0))
        visits(self.grower, days_ago_in_week(self.today, 1, 0, 2, 4))
        attended_class(self.grower, "Yoga", days_ago_in_week(self.today, 1, 2)[0])  # same day as a check-in
        self.stopper = member("Sami Stop", branch="Hamra")
        visits(self.stopper, days_ago_in_week(self.today, 2, 1, 3))
        # Jnah: one member, one visit last week.
        self.jnah = member("Jad Jnah", branch="Jnah")
        visits(self.jnah, days_ago_in_week(self.today, 1, 5))
        self.grow_seg = Segment.objects.create(name="Gina only", filters={"plans": ["Basic"], "branches": ["Hamra"],
                                                                         "visitsPerWeekMin": 0.75})
        marketing()
        staff_login(self.client, "nadine", PASSWORD)

    def get(self, **params):
        res = self.client.get("/api/segments/trends", params)
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def test_weekly_visits_per_active_member_with_totals(self):
        data = self.get(period="week")
        self.assertEqual(data["granularity"], "week")
        self.assertEqual(len(data["periods"]), 12)
        everyone = data["series"][0]
        self.assertEqual(everyone["name"], "All members")
        last, before = everyone["points"][-1], everyone["points"][-2]
        # Last week: Gina 3 visit days (the class was the same day as a check-in) + Jad 1.
        self.assertEqual(last["visits"], 4)
        self.assertEqual(last["activeMembers"], 3)
        self.assertEqual(last["visitsPerMember"], round(4 / 3, 2))
        self.assertEqual(before["visits"], 3)
        self.assertEqual(everyone["change"]["visits"], round((4 - 3) / 3 * 100, 1))

    def test_filter_by_branch(self):
        hamra = self.get(period="week", branch="Hamra")["series"][0]
        self.assertEqual(hamra["points"][-1]["visits"], 3)
        self.assertEqual(hamra["points"][-1]["activeMembers"], 2)
        jnah = self.get(period="week", branch="Jnah")["series"][0]
        self.assertEqual(jnah["points"][-1]["visits"], 1)

    def test_segment_series_and_change_marker(self):
        data = self.get(period="week", segments=str(self.grow_seg.pk))
        self.assertEqual([s["name"] for s in data["series"]], ["All members", "Gina only"])
        gina = data["series"][1]
        self.assertEqual(gina["size"], 1)
        self.assertEqual([p["visits"] for p in gina["points"][-2:]], [1, 3])
        self.assertEqual(gina["change"]["visitsPerMember"], 200.0)

    def test_per_member_not_raw_totals(self):
        """A segment twice as big with the same habits shows the same visits per member."""
        small = Segment.objects.create(name="Small", filters={"branches": ["Jnah"]})
        for i in range(3):
            m = member(f"Extra Jnah{i}", branch="Jnah")
            visits(m, days_ago_in_week(self.today, 1, 5))
        big = Segment.objects.create(name="Big", filters={"branches": ["Jnah"], "plans": ["Basic"]})
        data = self.get(period="week", segments=f"{small.pk},{big.pk}")
        s, b = data["series"][1], data["series"][2]
        self.assertEqual(s["points"][-1]["visitsPerMember"], b["points"][-1]["visitsPerMember"])

    def test_monthly_view(self):
        data = self.get(period="month")
        self.assertEqual(len(data["periods"]), 6)
        self.assertEqual(data["periods"][-1]["end"], (self.today.replace(day=1) - timedelta(days=1)).isoformat())

    def test_members_who_joined_later_are_not_active_earlier(self):
        Segment.objects.all().delete()
        newbie = member("Nora New", branch="Zalka", joined_days_ago=0)
        data = self.get(period="week", branch="Zalka")
        self.assertEqual(data["series"][0]["points"][-1]["activeMembers"], 0)
        self.assertEqual(data["series"][0]["size"], 1)
        self.assertEqual(newbie.branch, "Zalka")

    def test_validation(self):
        self.assertEqual(self.client.get("/api/segments/trends", {"period": "year"}).status_code, 400)
        self.assertEqual(self.client.get("/api/segments/trends", {"segments": "1,2,3,4"}).status_code, 400)
        self.assertEqual(self.client.get("/api/segments/trends", {"segments": "abc"}).status_code, 400)
        self.assertEqual(self.client.get("/api/segments/trends", {"segments": "999"}).status_code, 404)
        self.assertEqual(self.client.get("/api/segments/trends", {"branch": "Nowhere"}).status_code, 400)

    def test_branch_manager_is_held_to_their_branch(self):
        branch_manager()
        self.client.logout()
        staff_login(self.client, "hamrabm", PASSWORD)
        data = self.get(period="week")
        self.assertEqual(data["branches"], ["Hamra"])
        self.assertEqual(data["series"][0]["points"][-1]["visits"], 3)
        self.assertEqual(self.client.get("/api/segments/trends", {"branch": "Jnah"}).status_code, 403)
