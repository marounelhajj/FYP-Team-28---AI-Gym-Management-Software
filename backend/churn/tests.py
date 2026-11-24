from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from administration.testing import staff_login
from members.models import Member
from training.models import TrainingEvent

from . import config
from .features import week_start
from .jobs import refresh_due
from .learned import auc, train_for_branch
from .models import ChurnRun, ChurnScore, Method
from .scoring import refresh_branch, score_members
from .testing import PASSWORD, cancel, froze, member, payment, regular, staff, visits

VIEW = ["view_at_risk_members", "manage_at_risk_list"]


# User story (SCRUM-118): "As a branch manager, I want to view a ranked list
# of members at risk of leaving, so that I know who to contact first."
class RankingTests(TestCase):
    def setUp(self):
        self.healthy = member("Hala Healthy")
        regular(self.healthy, per_week=3)
        payment(self.healthy, 300, 60)

        self.fading = member("Fadi Fading", expires_in=10)
        regular(self.fading, per_week=3, recent_per_week=1)

        self.gone = member("Ghada Gone", expires_in=-5, status=Member.Status.FROZEN)
        regular(self.gone, per_week=3, skip_recent_weeks=5)
        froze(self.gone, 100)

    # AC: sorted by risk score.
    def test_list_is_sorted_by_risk_score(self):
        results = score_members("Hamra")
        ids = [member_id for member_id, _, _ in results]
        scores = [score for _, score, _ in results]
        self.assertEqual(ids, [self.gone.pk, self.fading.pk, self.healthy.pk])
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0 <= s <= 100 for s in scores))

    def test_healthy_member_scores_low_and_lapsed_member_high(self):
        scores = {member_id: score for member_id, score, _ in score_members("Hamra")}
        self.assertLess(scores[self.healthy.pk], config.LEVELS["rules"]["Medium"])
        self.assertGreaterEqual(scores[self.gone.pk], config.LEVELS["rules"]["High"])

    def test_reasons_are_the_largest_weighted_terms(self):
        reasons = {member_id: r for member_id, _, r in score_members("Hamra")}
        gone = [r["feature"] for r in reasons[self.gone.pk]]
        self.assertEqual(gone[0], "attendance_drop")
        self.assertLessEqual(len(gone), config.MAX_REASONS)
        points = [r["points"] for r in reasons[self.gone.pk]]
        self.assertEqual(points, sorted(points, reverse=True))

    def test_newer_members_attendance_is_averaged_over_their_own_weeks(self):
        from .features import live_history
        newer = member("Nadia Newer", joined_days_ago=42)
        # Three visits a week in their first two weeks, one a week since.
        visits(newer, [41, 39, 37, 34, 32, 30, 25, 18, 11, 4])
        f = live_history("Hamra").features(newer.pk, timezone.localdate(), live=True)
        self.assertEqual(f.visits_prior, 6)
        # 6 visits over the ~2 weeks they were a member before the recent window, not over 8 weeks.
        self.assertGreater(f.prior_per_week, 2.5)
        self.assertEqual(f.recent_per_week, 1.0)

    # Only members who haven't cancelled are scored.
    def test_cancelled_members_are_not_scored(self):
        cancel(self.fading, 2)
        ids = [member_id for member_id, _, _ in score_members("Hamra")]
        self.assertNotIn(self.fading.pk, ids)
        run = refresh_branch("Hamra")
        self.assertFalse(ChurnScore.objects.filter(run=run, member=self.fading).exists())

    def test_other_branches_members_are_not_in_the_list(self):
        other = member("Jana Jnah", branch="Jnah")
        ids = [member_id for member_id, _, _ in score_members("Hamra")]
        self.assertNotIn(other.pk, ids)


# AC: a rule-based score is used for branches with no history.
class FallbackTests(TestCase):
    def test_new_branch_without_history_uses_the_rules(self):
        newbie = member("Nora New", branch="Zalka", joined_days_ago=10)
        run = refresh_branch("Zalka")
        self.assertEqual(run.method, Method.RULES)
        self.assertIsNone(run.model)
        self.assertIn("not enough history", run.method_note)
        score = ChurnScore.objects.get(run=run, member=newbie)
        self.assertEqual(score.method, Method.RULES)
        self.assertEqual(score.model_version, "")
        self.assertIn("new_member", [r["feature"] for r in score.reasons])


def _branch_with_history(branch="Jnah", members=40, today=None):
    """Half the members drift away and cancel at different times; the rest stay."""
    today = today or timezone.localdate()
    out = []
    for i in range(members):
        m = member(f"Member{i} Test", branch=branch, joined_days_ago=300, expires_in=40)
        if i % 2 == 0:
            cancelled = 5 + (i * 7) % 150
            stop = cancelled + 30
            visits(m, list(range(300, stop, -2)))
            cancel(m, cancelled)
        else:
            visits(m, list(range(300, 0, -2)))
        out.append(m)
    return out


class LearnedModelTests(TestCase):
    def test_auc(self):
        self.assertEqual(auc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]), 1.0)
        self.assertEqual(auc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]), 0.0)
        self.assertEqual(auc([0.5, 0.5], [1, 0]), 0.5)

    def test_not_enough_history_returns_no_model(self):
        _branch_with_history(members=10)
        model, reason = train_for_branch("Jnah")
        self.assertIsNone(model)
        self.assertIn("not enough history", reason)

    def test_branch_with_enough_history_uses_the_learned_model(self):
        _branch_with_history(members=40)
        with mock.patch.object(config, "MIN_MEMBERS", 30), mock.patch.object(config, "MIN_CANCELLATIONS", 10):
            run = refresh_branch("Jnah")
        self.assertEqual(run.method, Method.MODEL, run.method_note)
        model = run.model
        self.assertTrue(model.usable)
        self.assertGreaterEqual(model.metrics["auc"], config.MIN_VALIDATION_AUC)
        self.assertEqual(model.features, list(config.RULE_WEIGHTS))
        scores = ChurnScore.objects.filter(run=run)
        self.assertTrue(scores.exists())
        self.assertTrue(all(s.method == Method.MODEL and s.model_version == model.version for s in scores))
        # Cancelled members are history, not people to call.
        self.assertFalse(scores.filter(member__status=Member.Status.CANCELLED).exists())

    def test_refresh_now_reuses_this_weeks_model(self):
        _branch_with_history(members=40)
        with mock.patch.object(config, "MIN_MEMBERS", 30), mock.patch.object(config, "MIN_CANCELLATIONS", 10):
            first = refresh_branch("Jnah")
            second = refresh_branch("Jnah", trigger=ChurnRun.Trigger.MANUAL)
        self.assertEqual(first.model_id, second.model_id)


# AC: the list is refreshed weekly.
class WeeklyRefreshTests(TestCase):
    def setUp(self):
        self.lina = member("Lina Hamra")
        regular(self.lina, per_week=2)

    def test_weekly_job_writes_a_snapshot_for_every_branch_once_a_week(self):
        refreshed = refresh_due()
        self.assertEqual(sorted(refreshed), sorted(Member.Branch.values))
        monday = week_start(timezone.localdate())
        run = ChurnRun.objects.get(branch="Hamra", week_start=monday)
        self.assertEqual(run.trigger, ChurnRun.Trigger.SCHEDULED)
        snapshot = ChurnScore.objects.get(branch="Hamra", week_start=monday, member=self.lina)
        self.assertEqual(snapshot.rank, 1)
        self.assertEqual(snapshot.method, Method.RULES)
        self.assertIn("visits_recent", snapshot.features)
        # Already done this week: nothing to do.
        self.assertEqual(refresh_due(), [])

    def test_next_week_gets_a_new_snapshot(self):
        refresh_due()
        next_monday = week_start(timezone.localdate()) + timedelta(days=7)
        with mock.patch("churn.jobs.timezone.localdate", return_value=next_monday):
            self.assertIn("Hamra", refresh_due(today=next_monday))

    def test_refreshing_the_same_week_replaces_the_snapshot(self):
        refresh_branch("Hamra")
        refresh_branch("Hamra", trigger=ChurnRun.Trigger.MANUAL)
        monday = week_start(timezone.localdate())
        self.assertEqual(ChurnScore.objects.filter(branch="Hamra", week_start=monday).count(), 1)

    def test_every_scoring_run_writes_a_training_event(self):
        run = refresh_branch("Hamra")
        event = TrainingEvent.objects.get(event_type=TrainingEvent.EventType.CHURN_SCORED, member=self.lina)
        self.assertEqual(event.branch, "Hamra")
        self.assertEqual(event.session_id, f"churn:{run.pk}")
        self.assertEqual(event.payload["method"], "rules")
        self.assertEqual(event.payload["rank"], 1)
        self.assertIn("score", event.payload)

    def test_management_command(self):
        out = StringIO()
        call_command("refresh_churn_scores", "--branch", "Hamra", stdout=out)
        self.assertIn("Hamra: 1 members scored (rules)", out.getvalue())
        self.assertEqual(ChurnRun.objects.get().trigger, ChurnRun.Trigger.COMMAND)

    def test_past_week_snapshot(self):
        as_of = timezone.localdate() - timedelta(days=21)
        call_command("refresh_churn_scores", "--branch", "Hamra", "--as-of", as_of.isoformat(), stdout=StringIO())
        self.assertTrue(ChurnScore.objects.filter(week_start=week_start(as_of), member=self.lina).exists())


# The page: branch managers see only their own branch, general managers any.
class AtRiskApiTests(TestCase):
    def setUp(self):
        staff("hamrabm", VIEW, branch="Hamra")
        staff("gm", [*VIEW, "view_all_branches"], job_title="General Manager")
        staff("desk", ["manage_members"], branch="Hamra", job_title="Receptionist")
        self.hamra = member("Hiba Hamra", expires_in=12)
        regular(self.hamra, per_week=3, recent_per_week=1)
        self.jnah = member("Jad Jnah", branch="Jnah")

    def get(self, branch=""):
        return self.client.get(f"/api/churn/at-risk?branch={branch}")

    def test_branch_manager_sees_their_own_branch(self):
        staff_login(self.client, "hamrabm", PASSWORD)
        res = self.get()
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body["branch"], "Hamra")
        self.assertFalse(body["canChooseBranch"])
        self.assertEqual([m["memberId"] for m in body["members"]], [self.hamra.pk])
        row = body["members"][0]
        self.assertEqual(row["rank"], 1)
        self.assertIn(row["level"], ["High", "Medium", "Low"])
        self.assertEqual(row["membershipEndsAt"], (timezone.localdate() + timedelta(days=12)).isoformat())
        self.assertIsNotNone(row["lastVisit"])
        self.assertEqual(body["run"]["trigger"], "on_demand")

    def test_branch_manager_cannot_see_another_branch(self):
        staff_login(self.client, "hamrabm", PASSWORD)
        self.assertEqual(self.get("Jnah").status_code, 403)
        self.assertEqual(self.client.post("/api/churn/refresh", {"branch": "Jnah"}, content_type="application/json").status_code, 403)
        self.assertFalse(ChurnRun.objects.filter(branch="Jnah").exists())

    def test_general_manager_can_pick_any_branch(self):
        staff_login(self.client, "gm", PASSWORD)
        body = self.get("Jnah").json()
        self.assertEqual(body["branch"], "Jnah")
        self.assertTrue(body["canChooseBranch"])
        self.assertEqual([m["memberId"] for m in body["members"]], [self.jnah.pk])

    def test_role_without_the_permission_is_refused(self):
        staff_login(self.client, "desk", PASSWORD)
        self.assertEqual(self.get().status_code, 403)

    def test_not_signed_in(self):
        self.assertEqual(self.get().status_code, 401)

    def test_refresh_now(self):
        staff_login(self.client, "hamrabm", PASSWORD)
        self.get()
        res = self.client.post("/api/churn/refresh", {}, content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["run"]["trigger"], "manual")
        self.assertEqual(res.json()["run"]["triggeredBy"], "Hamrabm")
        self.assertEqual(ChurnRun.objects.filter(branch="Hamra").count(), 2)
