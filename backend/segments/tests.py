from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from administration.testing import staff_login
from audit.models import AuditLog
from members.models import Member

from .clustering import SEED, cluster_profiles, name_for, refresh_due, run_clustering
from .filters import FilterError, clean_filters
from .models import ClusterGroup, ClusterRun, Segment
from .profiles import build_profiles
from .testing import (
    PASSWORD, attended_class, branch_manager, checkins, marketing, member, opt_out, pt_session, purchase, risk, staff, visits,
)


# User story (SCRUM-43): "As a marketing staff member, I want to segment
# members by behavior or demographics, so that I can send targeted
# communications."


class FilterValidationTests(TestCase):
    def test_normalises_lists_and_ranges(self):
        f = clean_filters({"branches": ["Jnah", "Hamra", "Hamra"], "visitsPerWeekMin": "1.5", "ptClient": True})
        self.assertEqual(f, {"branches": ["Hamra", "Jnah"], "visitsPerWeekMin": 1.5, "ptClient": True})

    def test_rejects_bad_input(self):
        for bad in (
            {"branches": ["Nowhere"]},
            {"riskLevels": ["Extreme"]},
            {"ageMin": 40, "ageMax": 30},
            {"tenureMonthsMin": 1.5},
            {"visitsPerWeekMin": "lots"},
            {"ptClient": "yes"},
            {"colour": "blue"},
            {"clusterGroup": 999},
            "not an object",
        ):
            with self.subTest(bad=bad), self.assertRaises(FilterError):
                clean_filters(bad)


class SegmentFilterTests(TestCase):
    """Each filter on its own, then combined with AND, through the live-count API."""

    def setUp(self):
        today = timezone.localdate()
        self.today = today
        # Ana: Hamra, Premium, 30 years old, joined 2 years ago, 3 visits a week,
        # does Yoga, has a PT, high churn risk, renews in 10 days.
        self.ana = member("Ana Active", branch="Hamra", joined_days_ago=730, expires_in=10)
        Member.objects.filter(pk=self.ana.pk).update(
            membership_plan="Premium", date_of_birth=date(today.year - 30, 1, 1),
        )
        visits(self.ana, [1, 3, 5, 8, 10, 12, 15, 17, 19, 22, 24, 26])
        attended_class(self.ana, "Yoga", 3)
        pt_session(self.ana, 5)
        risk(self.ana, "High")
        # Bilal: Jnah, Basic, 55, joined 2 months ago, 1 visit 40 days ago, no classes, low risk.
        self.bilal = member("Bilal Basic", branch="Jnah", joined_days_ago=60, expires_in=90)
        Member.objects.filter(pk=self.bilal.pk).update(date_of_birth=date(today.year - 55, 6, 1))
        visits(self.bilal, [40])
        risk(self.bilal, "Low")
        # Carla: Hamra, Basic, no date of birth, never visited, frozen.
        self.carla = member("Carla Cold", branch="Hamra", joined_days_ago=400, expires_in=None,
                            status=Member.Status.FROZEN)
        # Dani: Hamra, cancelled - outside the default statuses.
        self.dani = member("Dani Gone", branch="Hamra", status=Member.Status.CANCELLED)
        self.account = marketing()
        staff_login(self.client, "nadine", PASSWORD)

    def ids(self, filters):
        res = self.client.post("/api/segments/preview", {"filters": filters}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()["count"]

    def test_no_filters_is_active_and_frozen_members(self):
        self.assertEqual(self.ids({}), 3)
        self.assertEqual(self.ids({"statuses": ["Cancelled"]}), 1)

    def test_each_filter(self):
        cases = [
            ({"branches": ["Jnah"]}, 1),
            ({"plans": ["Premium"]}, 1),
            ({"ageMin": 25, "ageMax": 35}, 1),        # Carla has no date of birth: never matches
            ({"ageMin": 50}, 1),
            ({"tenureMonthsMin": 12}, 2),             # Ana and Carla
            ({"tenureMonthsMax": 3}, 1),              # Bilal
            ({"visitsPerWeekMin": 2}, 1),             # Ana
            ({"visitsPerWeekMax": 0}, 2),             # Bilal (none in 4 weeks) and Carla
            ({"daysSinceLastVisitMin": 30}, 2),       # Bilal, and Carla who never came
            ({"daysSinceLastVisitMax": 7}, 1),        # Ana
            ({"classTypes": ["Yoga"]}, 1),
            ({"classTypes": ["Spin"]}, 0),
            ({"ptClient": True}, 1),
            ({"ptClient": False}, 2),
            ({"riskLevels": ["High"]}, 1),
            ({"riskLevels": ["Low", "Medium"]}, 1),
            ({"renewalInDaysMax": 30}, 1),            # Ana; Carla has no end date
            ({"renewalInDaysMin": 60}, 1),            # Bilal
        ]
        for filters, expected in cases:
            with self.subTest(filters=filters):
                self.assertEqual(self.ids(filters), expected)

    def test_filters_combine_with_and(self):
        self.assertEqual(self.ids({"branches": ["Hamra"]}), 2)
        self.assertEqual(self.ids({"branches": ["Hamra"], "tenureMonthsMin": 12}), 2)
        self.assertEqual(self.ids({"branches": ["Hamra"], "tenureMonthsMin": 12, "classTypes": ["Yoga"]}), 1)
        self.assertEqual(self.ids({"branches": ["Hamra"], "classTypes": ["Yoga"], "riskLevels": ["Low"]}), 0)

    def test_live_count_follows_the_data(self):
        filters = {"visitsPerWeekMin": 1}
        self.assertEqual(self.ids(filters), 1)
        visits(self.bilal, [1, 2, 3, 4, 8])
        self.assertEqual(self.ids(filters), 2)

    def test_preview_rejects_bad_filters(self):
        res = self.client.post("/api/segments/preview", {"filters": {"ageMin": -1}}, content_type="application/json")
        self.assertEqual(res.status_code, 400)


class SegmentCrudTests(TestCase):
    def setUp(self):
        self.a = member("Ana Hamra", branch="Hamra")
        self.b = member("Bea Jnah", branch="Jnah")
        self.account = marketing()
        staff_login(self.client, "nadine", PASSWORD)

    def create(self, **body):
        return self.client.post("/api/segments", body, content_type="application/json")

    def test_create_edit_delete(self):
        res = self.create(name="  Hamra   members ", filters={"branches": ["Hamra"]})
        self.assertEqual(res.status_code, 201, res.content)
        data = res.json()
        self.assertEqual(data["name"], "Hamra members")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["source"], "rules")
        self.assertIn("Hamra", data["summary"])

        listed = self.client.get("/api/segments").json()["segments"]
        self.assertEqual([s["name"] for s in listed], ["Hamra members"])

        res = self.client.put(f"/api/segments/{data['id']}", {"name": "Everyone", "filters": {}},
                              content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["count"], 2)

        res = self.client.delete(f"/api/segments/{data['id']}")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Segment.objects.exists())
        actions = list(AuditLog.objects.filter(action__startswith="segment.").values_list("action", flat=True))
        self.assertEqual(sorted(actions), ["segment.deleted", "segment.saved", "segment.saved"])

    def test_names_are_required_and_unique(self):
        self.assertEqual(self.create(name="", filters={}).status_code, 400)
        self.assertEqual(self.create(name="Hamra", filters={}).status_code, 201)
        self.assertEqual(self.create(name="hamra", filters={}).status_code, 400)
        self.assertEqual(self.create(name="x" * 61, filters={}).status_code, 400)

    def test_view_only_roles_cannot_change_segments(self):
        branch_manager()
        self.client.logout()
        staff_login(self.client, "hamrabm", PASSWORD)
        self.assertEqual(self.create(name="Mine", filters={}).status_code, 403)
        self.assertEqual(self.client.get("/api/segments").status_code, 200)

    def test_roles_without_segment_permissions_are_refused(self):
        staff("desk", ["manage_members"], branch="Hamra")
        self.client.logout()
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.client.get("/api/segments").status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get("/api/segments").status_code, 401)


class BranchScopeTests(TestCase):
    """Org-wide for marketing and the general manager; a branch manager only sees their branch."""

    def setUp(self):
        for i in range(3):
            member(f"Hamra Person{i}", branch="Hamra")
        for i in range(2):
            member(f"Jnah Person{i}", branch="Jnah")
        self.everyone = Segment.objects.create(name="Everyone", filters={})
        self.jnah_only = Segment.objects.create(name="Jnah only", filters={"branches": ["Jnah"]})
        marketing()
        branch_manager()
        staff("gm", ["view_all_branches", "view_member_segments"], role_name="GM")

    def segments_for(self, username):
        self.client.logout()
        staff_login(self.client, username, PASSWORD)
        res = self.client.get("/api/segments")
        self.assertEqual(res.status_code, 200)
        return {s["name"]: s["count"] for s in res.json()["segments"]}

    def test_marketing_and_gm_are_org_wide(self):
        self.assertEqual(self.segments_for("nadine"), {"Everyone": 5, "Jnah only": 2})
        self.assertEqual(self.segments_for("gm"), {"Everyone": 5, "Jnah only": 2})

    def test_branch_manager_only_sees_their_branch(self):
        self.assertEqual(self.segments_for("hamrabm"), {"Everyone": 3})
        self.assertEqual(self.client.get(f"/api/segments/{self.jnah_only.pk}").status_code, 404)
        res = self.client.post("/api/segments/preview", {"filters": {}}, content_type="application/json")
        self.assertEqual(res.json()["count"], 3)
        meta = self.client.get("/api/segments/meta").json()
        self.assertEqual(meta["branches"], ["Hamra"])
        self.assertFalse(meta["canManage"])
        self.assertFalse(meta["canExportMembers"])

    def test_branch_manager_without_a_branch_is_refused(self):
        staff("floating", ["view_member_segments"], role_name="Floating BM")
        self.client.logout()
        staff_login(self.client, "floating", PASSWORD)
        self.assertEqual(self.client.get("/api/segments").status_code, 403)


class OptOutTests(TestCase):
    def test_opted_out_members_still_count_but_are_not_targetable(self):
        a, b = member("Ana One"), member("Bea Two")
        opt_out(b)
        marketing()
        staff_login(self.client, "nadine", PASSWORD)
        res = self.client.post("/api/segments/preview", {"filters": {}}, content_type="application/json").json()
        self.assertEqual((res["count"], res["optedOut"], res["targetable"]), (2, 1, 1))


class MemberProfileTests(TestCase):
    def test_member_can_set_their_date_of_birth(self):
        m = member("Mira Self")
        m.username = "mira"
        m.set_password(PASSWORD)
        m.save()
        self.client.post("/api/members/login", {"username": "mira", "password": PASSWORD}, content_type="application/json")
        res = self.client.patch("/api/members/me", {"dateOfBirth": "1995-04-02"}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["dateOfBirth"], "1995-04-02")
        future = (timezone.localdate() + timedelta(days=3)).isoformat()
        res = self.client.patch("/api/members/me", {"dateOfBirth": future}, content_type="application/json")
        self.assertEqual(res.status_code, 400)


def _behaviour_groups(today):
    """Three clearly different groups of active members."""
    made = []
    for i in range(8):   # evening class regulars
        m = member(f"Eve Regular{i}", joined_days_ago=500 + i, expires_in=30)
        visits(m, [1 + 2 * d for d in range(12)])
        for d in range(0, 24, 3):
            attended_class(m, "Spin", d + 1, hour=19)
        made.append(m)
    for i in range(8):   # morning PT clients
        m = member(f"Mo PT{i}", joined_days_ago=300 + i, expires_in=30)
        days = [d + 2 for d in range(0, 24, 4)]
        checkins(m, days, hour=7)
        for d in days:
            pt_session(m, d, hour=7, coach_username=f"pt{i}")
        made.append(m)
    for i in range(8):   # lapsing newcomers
        m = member(f"Lu Lapse{i}", joined_days_ago=70 + i, expires_in=5)
        visits(m, [50 + i])
        made.append(m)
    return made


class ClusteringTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        _behaviour_groups(self.today)

    def test_finds_distinct_named_groups(self):
        run = run_clustering(today=self.today)
        self.assertIn(run.k, range(3, 7))
        self.assertEqual(run.members_clustered, 24)
        self.assertGreater(run.silhouette, 0.4)
        self.assertEqual(len(run.candidates), 4)
        self.assertEqual(run.model_version, "kmeans-v1")
        groups = list(run.groups.all())
        self.assertEqual(sum(g.size for g in groups), 24)
        names = [g.name for g in groups]
        self.assertEqual(len(set(names)), len(names))
        self.assertTrue(any(n.startswith("Lapsing newcomers") for n in names), names)
        self.assertTrue(any("classes" in n and n.startswith("Evening") for n in names), names)
        self.assertTrue(any("PT" in n and n.startswith("Morning") for n in names), names)
        for g in groups:
            self.assertTrue(g.description)

    def test_deterministic_with_a_fixed_seed(self):
        from .clustering import active_profiles

        first = cluster_profiles(active_profiles(self.today), self.today, seed=SEED)
        second = cluster_profiles(active_profiles(self.today), self.today, seed=SEED)
        self.assertEqual(first, second)

    def test_only_active_members_are_clustered(self):
        Member.objects.filter(name__startswith="Lu Lapse").update(status=Member.Status.CANCELLED)
        run = run_clustering(today=self.today)
        self.assertEqual(run.members_clustered, 16)

    def test_too_few_members(self):
        Member.objects.exclude(name__startswith="Eve").delete()
        Member.objects.filter(name__in=["Eve Regular0", "Eve Regular1", "Eve Regular2"]).update(
            status=Member.Status.CANCELLED)
        run = run_clustering(today=self.today)
        self.assertIsNone(run.k)
        self.assertIn("at least", run.note)

    def test_weekly_refresh_runs_once_a_week(self):
        self.assertIsNotNone(refresh_due(self.today))
        self.assertIsNone(refresh_due(self.today))
        self.assertEqual(ClusterRun.objects.count(), 1)
        self.assertEqual(ClusterRun.objects.get().trigger, ClusterRun.Trigger.SCHEDULED)

    def test_management_command(self):
        out = StringIO()
        call_command("refresh_segment_clusters", "--force", stdout=out)
        self.assertIn("silhouette", out.getvalue())

    def test_save_a_suggested_segment_and_use_it(self):
        marketing()
        staff_login(self.client, "nadine", PASSWORD)
        res = self.client.post("/api/segments/clusters/run")
        self.assertEqual(res.status_code, 201)
        run = res.json()["run"]
        self.assertEqual(run["modelVersion"], "kmeans-v1")
        group = run["groups"][0]
        res = self.client.post(f"/api/segments/clusters/{group['id']}/save", {}, content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        saved = res.json()
        self.assertEqual(saved["source"], "cluster")
        self.assertEqual(saved["name"], group["name"])
        self.assertEqual(saved["count"], group["size"])
        # Still a normal segment: it can be narrowed with filters.
        res = self.client.put(f"/api/segments/{saved['id']}",
                              {"filters": {"clusterGroup": group["id"], "branches": ["Jnah"]}},
                              content_type="application/json")
        self.assertEqual(res.json()["count"], 0)
        listed = self.client.get("/api/segments/clusters").json()["run"]["groups"][0]
        self.assertEqual(listed["savedAs"][0]["id"], saved["id"])

    def test_branch_manager_cannot_run_clustering(self):
        branch_manager()
        staff_login(self.client, "hamrabm", PASSWORD)
        self.assertEqual(self.client.post("/api/segments/clusters/run").status_code, 403)
        self.assertEqual(self.client.get("/api/segments/clusters").status_code, 200)


class NamingTests(TestCase):
    def centre(self, **kw):
        base = {"visitsPerWeek": 3, "meanHour": 18.5, "classShare": 0.6, "ptShare": 0.0, "tenureMonths": 14,
                "recencyDays": 2, "spend90": 120}
        return {**base, **kw}

    def test_names_from_centres(self):
        self.assertEqual(name_for(self.centre()), "Evening regulars, mostly classes")
        self.assertEqual(name_for(self.centre(meanHour=8, ptShare=0.5, classShare=0.1)),
                         "Morning regulars, training with a PT")
        self.assertEqual(name_for(self.centre(recencyDays=40, tenureMonths=2)), "Lapsing newcomers")
        self.assertEqual(name_for(self.centre(visitsPerWeek=1.5, classShare=0.0, meanHour=13)),
                         "Daytime weekly visitors, mostly gym floor")


class ProfileTests(TestCase):
    def test_a_class_and_a_check_in_on_the_same_day_is_one_visit(self):
        m = member("Sam Same")
        visits(m, [2])
        attended_class(m, "Yoga", 2)
        p = build_profiles(Member.objects.filter(pk=m.pk))[m.pk]
        self.assertEqual(len(p.visit_days), 1)
        self.assertEqual(p.class_visits_90, 1)

    def test_spend_counts_payments_and_shop(self):
        from .testing import at  # noqa: F401
        m = member("Pat Pay")
        purchase(m, "Drinks", 3, quantity=2, price="2.50")
        p = build_profiles(Member.objects.filter(pk=m.pk))[m.pk]
        self.assertEqual(float(p.spend_90), 5.0)

    def test_cancelled_pt_sessions_do_not_make_a_pt_client(self):
        m = member("Pia Cancel")
        pt_session(m, 3, cancelled=True)
        p = build_profiles(Member.objects.filter(pk=m.pk))[m.pk]
        self.assertFalse(p.pt_client)
