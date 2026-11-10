from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from audit.models import AuditLog
from training.models import TrainingEvent

from . import config
from .models import ChurnRun, ChurnScore, RetentionCall

# How well the call list works (SCRUM-120: "accuracy is tracked against
# completed calls").
#
# For every week's list, the "listed" members are the top `call_capacity`
# ranks - the week's call list. From the calls staff logged (SCRUM-68) and
# the cancellations that happened afterwards it reports:
#
#   this week   listed, contacted (any outcome but "no answer"), still to
#               call, saved, cancelled anyway
#   all weeks   the same, summed over every week's list
#   precision   for finished weeks (LABEL_DAYS since the list was made):
#               the share of listed members who cancelled within 30 days
#               (precision at N), next to the share of the branch's other
#               scored members who did. A useful list catches far more
#               leavers than the rest. Members staff saved will drag the
#               listed rate down - which is the point of calling them - so
#               the panel shows both numbers side by side.
#
# Until there are ACCURACY_MIN_WEEKS finished weeks with at least
# ACCURACY_MIN_LISTED listed members, precision is "not enough data yet".


def _cancellations(member_ids):
    out = {}
    for member_id, at in (
        TrainingEvent.objects.filter(member_id__in=member_ids, event_type=TrainingEvent.EventType.CANCELLATION)
        .order_by("occurred_at").values_list("member_id", "occurred_at")
    ):
        out.setdefault(member_id, timezone.localtime(at).date())
    for target_id, at in (
        AuditLog.objects.filter(target_type="member", target_id__in=[str(i) for i in member_ids],
                                action=AuditLog.Action.MEMBER_CANCELLED)
        .order_by("created_at").values_list("target_id", "created_at")
    ):
        out.setdefault(int(target_id), timezone.localtime(at).date())
    return out


def _rate(part, whole):
    return round(part / whole, 3) if whole else None


def call_counts(calls_by_member, member_ids):
    contacted = saved = cancelled_anyway = no_answer_only = 0
    for member_id in member_ids:
        calls = calls_by_member.get(member_id, [])
        outcomes = {c.outcome for c in calls}
        if any(c.contacted for c in calls):
            contacted += 1
        elif outcomes:
            no_answer_only += 1
        if RetentionCall.Outcome.SAVED in outcomes:
            saved += 1
        if RetentionCall.Outcome.CANCELLED_ANYWAY in outcomes:
            cancelled_anyway += 1
    return {
        "listed": len(member_ids), "contacted": contacted, "noAnswer": no_answer_only,
        "toCall": len(member_ids) - contacted, "saved": saved, "cancelledAnyway": cancelled_anyway,
    }


def branch_accuracy(branch, today=None):
    today = today or timezone.localdate()
    # The latest run of each week is that week's list.
    runs = {}
    for run in ChurnRun.objects.filter(branch=branch).order_by("week_start", "ran_at", "id"):
        runs[run.week_start] = run
    if not runs:
        return None

    scores = defaultdict(list)
    for s in ChurnScore.objects.filter(run__in=runs.values()).values("week_start", "member_id", "rank"):
        scores[s["week_start"]].append(s)
    calls = defaultdict(lambda: defaultdict(list))
    for call in RetentionCall.objects.filter(branch=branch, week_start__in=list(runs)):
        calls[call.week_start][call.member_id].append(call)
    cancelled = _cancellations({s["member_id"] for rows in scores.values() for s in rows})

    totals = defaultdict(int)
    this_week = None
    finished = {"weeks": 0, "listed": 0, "listedCancelled": 0, "others": 0, "othersCancelled": 0,
                "contacted": 0, "contactedCancelled": 0}
    for monday, run in sorted(runs.items()):
        rows = scores.get(monday, [])
        listed = [s["member_id"] for s in rows if s["rank"] <= run.call_capacity]
        counts = call_counts(calls[monday], listed)
        for key, value in counts.items():
            totals[key] += value
        if monday == max(runs):
            this_week = {"weekStart": monday, "capacity": run.call_capacity, **counts}

        if run.as_of + timedelta(days=config.LABEL_DAYS) > today:
            continue
        horizon = run.as_of + timedelta(days=config.LABEL_DAYS)
        left = {m for m, day in cancelled.items() if run.as_of < day <= horizon}
        others = [s["member_id"] for s in rows if s["rank"] > run.call_capacity]
        contacted = [m for m in listed if any(c.contacted for c in calls[monday].get(m, []))]
        finished["weeks"] += 1
        finished["listed"] += len(listed)
        finished["listedCancelled"] += sum(1 for m in listed if m in left)
        finished["others"] += len(others)
        finished["othersCancelled"] += sum(1 for m in others if m in left)
        finished["contacted"] += len(contacted)
        finished["contactedCancelled"] += sum(1 for m in contacted if m in left)

    enough = finished["weeks"] >= config.ACCURACY_MIN_WEEKS and finished["listed"] >= config.ACCURACY_MIN_LISTED
    precision = _rate(finished["listedCancelled"], finished["listed"])
    others_rate = _rate(finished["othersCancelled"], finished["others"])
    return {
        "thisWeek": this_week,
        "allWeeks": {"weeks": len(runs), **dict(totals)},
        "precision": {
            "enough": enough,
            "finishedWeeks": finished["weeks"],
            "listed": finished["listed"],
            "listedCancelled": finished["listedCancelled"],
            "precisionAtN": precision if enough else None,
            "others": finished["others"],
            "othersCancelled": finished["othersCancelled"],
            "othersRate": others_rate if enough else None,
            "lift": round(precision / others_rate, 1) if enough and precision is not None and others_rate else None,
            "contacted": finished["contacted"],
            "contactedCancelled": finished["contactedCancelled"],
            "contactedRate": _rate(finished["contactedCancelled"], finished["contacted"]) if enough else None,
            "labelDays": config.LABEL_DAYS,
            "minWeeks": config.ACCURACY_MIN_WEEKS,
            "minListed": config.ACCURACY_MIN_LISTED,
        },
    }
