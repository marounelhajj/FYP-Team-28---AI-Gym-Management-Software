import math
import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from members.models import Member

from .models import ClusterGroup, ClusterRun
from .profiles import RECENT_DAYS, build_profiles

# "Suggested segments" (SCRUM-43): behavioural clusters of active members.
#
# Features, one row per active member:
#   visitsPerWeek   visit days a week over the last 4 weeks
#   meanHour        average time of day they come in (last 90 days)
#   classShare      share of their recent activity that was classes
#   ptShare         share that was personal training
#                   (gym floor is the rest, 1 - classShare - ptShare)
#   tenureMonths    how long they've been a member
#   recencyDays     days since their last visit (capped at 120)
#   spend90         membership payments + shop purchases in the last 90 days
#
# The skewed ones (tenure, recency, spend) are log-scaled, then every
# feature is standardised (mean 0, sd 1) so none dominates. k-means with
# k-means++ seeding runs for k = 3..6 with a fixed seed (same data, same
# result), and the k with the best silhouette score wins. Each cluster gets
# a name and a description from its centre, in plain units.
#
# Plain Python on purpose: the project has no numpy/scikit-learn, and the
# churn model (churn/learned.py) is plain Python too. A few hundred members
# x 7 features is small.

MODEL_VERSION = "kmeans-v1"
SEED = 28
K_RANGE = range(3, 7)
N_INIT = 6
MAX_ITER = 100
MIN_MEMBERS = 12
SILHOUETTE_SAMPLE = 900
RECENCY_CAP = 120
NO_VISIT_HOUR = None

FEATURES = ["visitsPerWeek", "meanHour", "classShare", "ptShare", "tenureMonths", "recencyDays", "spend90"]
LOG_FEATURES = {"tenureMonths", "recencyDays", "spend90"}


def _raw_features(profiles, today):
    rows, ids = [], []
    hours = [h for p in profiles for h in p.visit_hours_90]
    default_hour = sum(hours) / len(hours) if hours else 12.0
    for p in profiles:
        activity = p.class_visits_90 + p.pt_sessions_90 + p.gym_visits_90
        recency = p.days_since_last_visit(today)
        rows.append({
            "visitsPerWeek": p.visits_per_week(),
            "meanHour": (sum(p.visit_hours_90) / len(p.visit_hours_90)) if p.visit_hours_90 else default_hour,
            "classShare": p.class_visits_90 / activity if activity else 0.0,
            "ptShare": p.pt_sessions_90 / activity if activity else 0.0,
            "tenureMonths": p.tenure_months(today),
            "recencyDays": float(min(RECENCY_CAP, recency if recency is not None else RECENCY_CAP)),
            "spend90": float(p.spend_90),
        })
        ids.append(p.id)
    return ids, rows


def _scale(rows):
    transformed = [[math.log1p(r[f]) if f in LOG_FEATURES else r[f] for f in FEATURES] for r in rows]
    scaler = {}
    n = len(transformed)
    for j, name in enumerate(FEATURES):
        col = [row[j] for row in transformed]
        mean = sum(col) / n
        sd = math.sqrt(sum((x - mean) ** 2 for x in col) / n) or 1.0
        scaler[name] = [mean, sd]
        for row in transformed:
            row[j] = (row[j] - mean) / sd
    return transformed, scaler


def _dist2(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _kmeans_pp(points, k, rng):
    centres = [list(points[rng.randrange(len(points))])]
    d2 = [_dist2(p, centres[0]) for p in points]
    while len(centres) < k:
        total = sum(d2)
        if total == 0:
            centres.append(list(points[rng.randrange(len(points))]))
        else:
            target, acc = rng.random() * total, 0.0
            for i, w in enumerate(d2):
                acc += w
                if acc >= target:
                    centres.append(list(points[i]))
                    break
            else:
                centres.append(list(points[-1]))
        d2 = [min(d, _dist2(p, centres[-1])) for p, d in zip(points, d2)]
    return centres


def kmeans(points, k, rng):
    """Best of N_INIT k-means++ runs: (labels, centres, inertia)."""
    best = None
    dims = len(points[0])
    for _ in range(N_INIT):
        centres = _kmeans_pp(points, k, rng)
        labels = [0] * len(points)
        for _ in range(MAX_ITER):
            new = [min(range(k), key=lambda c: _dist2(p, centres[c])) for p in points]
            sums = [[0.0] * dims for _ in range(k)]
            counts = [0] * k
            for p, c in zip(points, new):
                counts[c] += 1
                for j in range(dims):
                    sums[c][j] += p[j]
            for c in range(k):
                if counts[c]:
                    centres[c] = [s / counts[c] for s in sums[c]]
                else:
                    # Empty cluster: restart it on the point furthest from its centre.
                    far = max(range(len(points)), key=lambda i: _dist2(points[i], centres[new[i]]))
                    centres[c] = list(points[far])
            if new == labels:
                break
            labels = new
        inertia = sum(_dist2(p, centres[c]) for p, c in zip(points, labels))
        if best is None or inertia < best[2]:
            best = (labels, [list(c) for c in centres], inertia)
    return best


def silhouette(points, labels, rng):
    """Mean silhouette score; on a seeded sample when there are many members."""
    idx = list(range(len(points)))
    if len(idx) > SILHOUETTE_SAMPLE:
        idx = sorted(rng.sample(idx, SILHOUETTE_SAMPLE))
    clusters = sorted(set(labels[i] for i in idx))
    if len(clusters) < 2:
        return -1.0
    members = {c: [i for i in idx if labels[i] == c] for c in clusters}
    total = 0.0
    for i in idx:
        own = labels[i]
        dist = {c: [math.sqrt(_dist2(points[i], points[j])) for j in members[c] if j != i] for c in clusters}
        if not dist[own]:
            continue  # a singleton scores 0
        a = sum(dist[own]) / len(dist[own])
        b = min(sum(d) / len(d) for c, d in dist.items() if c != own and d)
        total += (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return total / len(idx)


# --- Names and descriptions from a cluster centre ---------------------------

def _time_word(hour):
    if hour < 11:
        return "Morning"
    if hour >= 17:
        return "Evening"
    return "Daytime"


def _mix_phrase(class_share, pt_share):
    if pt_share >= 0.25:
        return "training with a PT"
    if class_share >= 0.5:
        return "mostly classes"
    if class_share >= 0.2:
        return "classes and gym floor"
    return "mostly gym floor"


def name_for(c):
    lapsing = c["recencyDays"] >= 21 or c["visitsPerWeek"] < 0.5
    if lapsing:
        if c["tenureMonths"] < 4:
            return "Lapsing newcomers"
        if c["tenureMonths"] >= 24:
            return "Lapsing long-timers"
        return "Lapsing members"
    if c["visitsPerWeek"] >= 2.5:
        freq = "regulars"
    elif c["visitsPerWeek"] >= 1.2:
        freq = "weekly visitors"
    else:
        freq = "occasional visitors"
    name = f"{_time_word(c['meanHour'])} {freq}, {_mix_phrase(c['classShare'], c['ptShare'])}"
    if c["tenureMonths"] < 3:
        name = "New " + name[0].lower() + name[1:]
    return name


def _hour_text(hour):
    h = int(round(hour)) % 24
    suffix = "am" if h < 12 else "pm"
    return f"{(h % 12) or 12}{suffix}"


def description_for(c):
    gym = max(0.0, 1 - c["classShare"] - c["ptShare"])
    if c["visitsPerWeek"] < 0.1:
        visits = "Have not visited in the last 4 weeks"
    else:
        visits = f"Visit about {c['visitsPerWeek']:.1f} times a week, usually around {_hour_text(c['meanHour'])}"
    return (
        f"{visits}; activity is {round(c['classShare'] * 100)}% classes, {round(c['ptShare'] * 100)}% PT and "
        f"{round(gym * 100)}% gym floor. Members for {c['tenureMonths']:.0f} months on average, last seen "
        f"{c['recencyDays']:.0f} days ago, spending about ${c['spend90']:.0f} in 90 days."
    )


def _plain_centre(rows, member_rows):
    return {f: round(sum(rows[i][f] for i in member_rows) / len(member_rows), 2) for f in FEATURES}


def _unique(names, centres):
    seen = {}
    out = []
    for name, c in zip(names, centres):
        if name in seen:
            seen[name] += 1
            name = f"{name} ({'newer' if c['tenureMonths'] < 12 else 'long-standing'})"
            if name in out:
                name = f"{name} {seen[name.split(' (')[0]]}"
        else:
            seen[name] = 1
        out.append(name)
    return out


# --- The job ----------------------------------------------------------------

def cluster_profiles(profiles, today, seed=SEED):
    """Pure computation, no database writes. Returns a dict describing the result."""
    profiles = sorted(profiles, key=lambda p: p.id)
    if len(profiles) < MIN_MEMBERS:
        return {"k": None, "silhouette": None, "candidates": [], "groups": [], "scaler": {},
                "n": len(profiles), "note": f"Needs at least {MIN_MEMBERS} active members to suggest segments."}
    ids, rows = _raw_features(profiles, today)
    points, scaler = _scale(rows)
    candidates, best = [], None
    for k in K_RANGE:
        if k >= len(points):
            break
        rng = random.Random(seed * 100 + k)
        labels, _, _ = kmeans(points, k, rng)
        score = silhouette(points, labels, random.Random(seed))
        candidates.append({"k": k, "silhouette": round(score, 4)})
        if best is None or score > best[1] + 1e-9:
            best = (k, score, labels)
    k, score, labels = best
    clusters = {}
    for i, label in enumerate(labels):
        clusters.setdefault(label, []).append(i)
    ordered = sorted(clusters.values(), key=lambda rows_: (-len(rows_), min(ids[i] for i in rows_)))
    centres = [_plain_centre(rows, members) for members in ordered]
    names = _unique([name_for(c) for c in centres], centres)
    groups = [
        {
            "position": pos, "name": names[pos], "description": description_for(centres[pos]),
            "size": len(members), "centroid": centres[pos], "member_ids": sorted(ids[i] for i in members),
        }
        for pos, members in enumerate(ordered)
    ]
    return {"k": k, "silhouette": round(score, 4), "candidates": candidates, "groups": groups,
            "scaler": {f: [round(m, 4), round(s, 4)] for f, (m, s) in scaler.items()}, "n": len(profiles), "note": ""}


def active_profiles(today):
    members = Member.objects.filter(status=Member.Status.ACTIVE).exclude(email__endswith="@deleted.invalid")
    return list(build_profiles(members, today).values())


def run_clustering(trigger=ClusterRun.Trigger.MANUAL, by=None, today=None):
    today = today or timezone.localdate()
    result = cluster_profiles(active_profiles(today), today)
    with transaction.atomic():
        run = ClusterRun.objects.create(
            week_start=today - timedelta(days=today.weekday()), trigger=trigger, triggered_by=by,
            model_version=MODEL_VERSION, seed=SEED, k=result["k"], silhouette=result["silhouette"],
            candidates=result["candidates"], members_clustered=result["n"], feature_names=FEATURES,
            scaler=result["scaler"], note=result["note"],
        )
        ClusterGroup.objects.bulk_create([ClusterGroup(run=run, **g) for g in result["groups"]])
    return run


def refresh_due(today=None):
    """The weekly run, called from the churn job (churn/jobs.py). Returns the new run or None."""
    today = today or timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    if ClusterRun.objects.filter(week_start=monday).exists():
        return None
    return run_clustering(trigger=ClusterRun.Trigger.SCHEDULED, today=today)


def latest_run():
    return ClusterRun.objects.prefetch_related("groups").first()


__all__ = ["run_clustering", "refresh_due", "latest_run", "cluster_profiles", "RECENT_DAYS"]
