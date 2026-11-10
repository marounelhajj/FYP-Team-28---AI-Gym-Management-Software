from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from members.models import Member
from training.events import log_training_event
from training.models import TrainingEvent

from . import config, learned
from .features import FEATURE_KEYS, BranchHistory, day_end, live_history, signals, week_start
from .models import ChurnModel, ChurnRun, ChurnScore, Method, call_capacity

# The single scoring interface for the at-risk list (SCRUM-118):
#
#   score_members(branch) -> [(member_id, score 0-100, reasons), ...]
#
# with two implementations behind it. A branch uses its learned model when
# it has enough labelled history (see learned.py), and the rule-based score
# otherwise - so a new branch always gets a list. `reasons` is the top
# contributing features, largest first: [{"feature", "points"}].


@dataclass
class MemberScore:
    member_id: int
    score: int
    reasons: list
    features: dict
    method: str
    model_version: str = ""
    level: str = ""


@dataclass
class BranchScores:
    method: str
    model: ChurnModel | None
    note: str
    scores: list = field(default_factory=list)


def level_for(score, method):
    bands = config.LEVELS[method]
    if score >= bands["High"]:
        return "High"
    if score >= bands["Medium"]:
        return "Medium"
    return "Low"


def _top_reasons(points_by_feature):
    ranked = sorted(points_by_feature.items(), key=lambda kv: -kv[1])
    return [
        {"feature": key, "points": round(points, 1)}
        for key, points in ranked if points >= config.MIN_REASON_POINTS
    ][:config.MAX_REASONS]


def rule_score(feature_values):
    sig = signals(feature_values)
    points = {key: config.RULE_WEIGHTS[key] * sig[key] for key in FEATURE_KEYS}
    return round(sum(points.values())), _top_reasons(points)


def model_score(model, feature_values):
    sig = signals(feature_values)
    row = [sig[k] for k in model.features]
    params = learned.params_of(model)
    probability = learned.predict(params, row)
    # A contribution is in log-odds; scale to "points" so the same minimum
    # applies. Only features that push the risk up are reasons.
    pushes = learned.contributions(params, row)
    points = {key: 10 * value for key, value in zip(model.features, pushes)}
    return round(100 * probability), _top_reasons(points)


def current_model(branch, as_of):
    # One training per branch per week: a "Refresh now" reuses this week's model.
    monday = week_start(as_of)
    existing = ChurnModel.objects.filter(branch=branch, trained_as_of__gte=monday, trained_as_of__lte=as_of).first()
    if existing is not None:
        if existing.usable:
            return existing, ""
        return None, f"the model didn't validate well enough (AUC {existing.metrics.get('auc')})"
    return learned.train_for_branch(branch, as_of=as_of)


def score_branch(branch, as_of=None, method=None):
    """Scores every member of the branch as of a date. method forces 'rules' or 'model'."""
    today = timezone.localdate()
    as_of = as_of or today
    live = as_of == today
    if live:
        history = live_history(branch)
        member_ids = list(history.members)
    else:
        history = BranchHistory.for_branch(branch)
        member_ids = history.eligible(as_of)

    model, note = (None, "rule-based score requested") if method == Method.RULES else current_model(branch, as_of)
    use_model = model is not None
    result = BranchScores(method=Method.MODEL if use_model else Method.RULES, model=model,
                          note="" if use_model else f"Rule-based: {note}")
    for member_id in member_ids:
        values = history.features(member_id, as_of, live=live).as_dict()
        if use_model:
            score, reasons = model_score(model, values)
        else:
            score, reasons = rule_score(values)
        result.scores.append(MemberScore(
            member_id=member_id, score=max(0, min(100, score)), reasons=reasons, features=values,
            method=result.method, model_version=model.version if use_model else "",
            level=level_for(score, result.method),
        ))
    result.scores.sort(key=lambda s: (-s.score, s.member_id))
    return result


def score_members(branch_id, as_of=None):
    return [(s.member_id, s.score, s.reasons) for s in score_branch(branch_id, as_of).scores]


# Scores the branch and saves it as the snapshot for the week containing
# `as_of`, replacing any earlier snapshot of that week. Every member scored
# also gets a "churn_scored" training event, so the scores can be checked
# against what members actually did later.
def refresh_branch(branch, *, as_of=None, trigger=ChurnRun.Trigger.SCHEDULED, staff=None):
    as_of = as_of or timezone.localdate()
    monday = week_start(as_of)
    scored = score_branch(branch, as_of)
    with transaction.atomic():
        ChurnScore.objects.filter(branch=branch, week_start=monday).delete()
        run = ChurnRun.objects.create(
            branch=branch, week_start=monday, as_of=as_of, method=scored.method, model=scored.model,
            method_note=scored.note[:255], members_scored=len(scored.scores), trigger=trigger, triggered_by=staff,
            call_capacity=call_capacity(branch),
        )
        ChurnScore.objects.bulk_create([
            ChurnScore(
                run=run, branch=branch, week_start=monday, member_id=s.member_id, rank=rank, score=s.score,
                level=s.level, method=s.method, model_version=s.model_version, reasons=s.reasons, features=s.features,
            )
            for rank, s in enumerate(scored.scores, start=1)
        ])
    members = Member.objects.in_bulk([s.member_id for s in scored.scores])
    # A backfilled past week is logged as of that day, not today.
    occurred_at = None if as_of == timezone.localdate() else day_end(as_of) - timedelta(minutes=1)
    for rank, s in enumerate(scored.scores, start=1):
        log_training_event(
            TrainingEvent.EventType.CHURN_SCORED, member=members[s.member_id], branch=branch,
            session_id=f"churn:{run.pk}", occurred_at=occurred_at,
            payload={
                "runId": run.pk, "weekStart": monday.isoformat(), "asOf": as_of.isoformat(), "rank": rank,
                "score": s.score, "level": s.level, "method": s.method, "modelVersion": s.model_version,
                "reasons": [r["feature"] for r in s.reasons],
            },
        )
    return run


def latest_run(branch, monday):
    return ChurnRun.objects.filter(branch=branch, week_start=monday).first()


def ensure_current(branch, trigger=ChurnRun.Trigger.ON_DEMAND):
    monday = week_start(timezone.localdate())
    run = latest_run(branch, monday)
    return run or refresh_branch(branch, trigger=trigger)
