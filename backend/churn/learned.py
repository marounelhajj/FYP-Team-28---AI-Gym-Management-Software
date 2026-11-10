import math
from datetime import timedelta

from django.utils import timezone

from . import config
from .features import FEATURE_KEYS, BranchHistory, signals
from .models import ChurnModel

# The learned churn model: a plain logistic regression on the same seven
# signals the rule-based score uses, trained per branch.
#
# Why logistic regression: it is explainable (each coefficient x the
# member's distance from the branch average is that feature's push on the
# score, which is what the reasons are built from), it needs no extra
# dependency, and with seven inputs it trains in a second in pure Python.
#
# Training data: every CUTOFF_STEP_DAYS, for every member who was a member
# at that cutoff, the features as of the cutoff and the label "cancelled
# within the next LABEL_DAYS". Only cutoffs whose label window has fully
# passed (before the `as_of` date we are training for) are used, so the
# model never learns from the future.
#
# Validation: the newest HOLDOUT_SHARE of cutoffs are held out; the model
# trained on the older ones is scored on them (AUC, and precision in the
# top N vs the base rate). The model is only used if that AUC reaches
# MIN_VALIDATION_AUC; the final model is then refit on every cutoff.


def _sigmoid(z):
    if z < -35:
        return 0.0
    if z > 35:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _standardize(rows):
    n = len(rows)
    width = len(rows[0])
    means = [sum(r[j] for r in rows) / n for j in range(width)]
    stds = []
    for j in range(width):
        var = sum((r[j] - means[j]) ** 2 for r in rows) / n
        stds.append(math.sqrt(var) or 1.0)
    return means, stds


def fit(rows, labels, epochs=None, learning_rate=None, l2=None):
    epochs = epochs or config.TRAIN_EPOCHS
    learning_rate = learning_rate or config.LEARNING_RATE
    l2 = config.L2_PENALTY if l2 is None else l2
    means, stds = _standardize(rows)
    xs = [[(v - means[j]) / stds[j] for j, v in enumerate(r)] for r in rows]
    n, width = len(xs), len(xs[0])
    weights = [0.0] * width
    base = sum(labels) / n
    bias = math.log(base / (1 - base)) if 0 < base < 1 else 0.0
    for _ in range(epochs):
        grad_w = [0.0] * width
        grad_b = 0.0
        for x, y in zip(xs, labels):
            err = _sigmoid(bias + sum(w * v for w, v in zip(weights, x))) - y
            grad_b += err
            for j in range(width):
                grad_w[j] += err * x[j]
        bias -= learning_rate * grad_b / n
        for j in range(width):
            weights[j] -= learning_rate * (grad_w[j] / n + l2 * weights[j])
    return {"coefficients": weights, "intercept": bias, "means": means, "stds": stds}


def predict(params, row):
    z = params["intercept"]
    for j, v in enumerate(row):
        z += params["coefficients"][j] * (v - params["means"][j]) / params["stds"][j]
    return _sigmoid(z)


# Each feature's push on the log-odds relative to an average member.
def contributions(params, row):
    return [
        params["coefficients"][j] * (v - params["means"][j]) / params["stds"][j]
        for j, v in enumerate(row)
    ]


def auc(scores, labels):
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    # Rank-based (Mann-Whitney), ties count half.
    ranked = sorted(zip(scores, labels), key=lambda p: p[0])
    rank_sum, i = 0.0, 0
    while i < len(ranked):
        j = i
        while j < len(ranked) and ranked[j][0] == ranked[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2
        rank_sum += avg_rank * sum(1 for k in range(i, j) if ranked[k][1])
        i = j
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def cutoffs(history, as_of):
    first = history.earliest_activity()
    if first is None:
        return []
    start = first + timedelta(weeks=config.RECENT_WEEKS + config.PRIOR_WEEKS)
    last = as_of - timedelta(days=config.LABEL_DAYS)
    out, day = [], last
    while day >= start:
        out.append(day)
        day -= timedelta(days=config.CUTOFF_STEP_DAYS)
    return sorted(out)


def training_examples(history, as_of):
    examples = []
    for cutoff in cutoffs(history, as_of):
        horizon = cutoff + timedelta(days=config.LABEL_DAYS)
        for member_id in history.eligible(cutoff):
            cancelled = history.cancellation_date(member_id)
            label = 1 if cancelled is not None and cutoff < cancelled <= horizon else 0
            sig = signals(history.features(member_id, cutoff))
            examples.append((cutoff, member_id, [sig[k] for k in FEATURE_KEYS], label))
    return examples


def _precision_at_n(scored, n):
    top = sorted(scored, key=lambda p: -p[0])[:n]
    return sum(y for _, y in top) / len(top) if top else None


def train_for_branch(branch, as_of=None, top_n=20):
    """Trains (and stores) a model for the branch, or returns (None, reason)."""
    as_of = as_of or timezone.localdate()
    history = BranchHistory.for_branch(branch)
    examples = training_examples(history, as_of)
    members = {member_id for _, member_id, _, _ in examples}
    cancellations = {member_id for _, member_id, _, y in examples if y}
    if len(cancellations) < config.MIN_CANCELLATIONS or len(members) < config.MIN_MEMBERS:
        return None, (
            f"not enough history yet ({len(cancellations)} cancellations and {len(members)} members in the "
            f"training window; the model needs {config.MIN_CANCELLATIONS} and {config.MIN_MEMBERS})"
        )

    dates = sorted({c for c, _, _, _ in examples})
    holdout_count = max(1, round(len(dates) * config.HOLDOUT_SHARE))
    holdout_dates = set(dates[-holdout_count:])
    train = [e for e in examples if e[0] not in holdout_dates]
    test = [e for e in examples if e[0] in holdout_dates]
    if not train or not any(y for *_, y in train):
        return None, "not enough cancellations before the validation period"

    trial = fit([r for _, _, r, _ in train], [y for *_, y in train])
    test_scores = [predict(trial, r) for _, _, r, _ in test]
    test_labels = [y for *_, y in test]
    validation_auc = auc(test_scores, test_labels)
    precisions = []
    for day in sorted(holdout_dates):
        scored = [(s, y) for s, (c, _, _, y) in zip(test_scores, test) if c == day]
        p = _precision_at_n(scored, top_n)
        if p is not None:
            precisions.append(p)

    final = fit([r for _, _, r, _ in examples], [y for *_, y in examples])
    metrics = {
        "auc": round(validation_auc, 3) if validation_auc is not None else None,
        "precisionAtN": round(sum(precisions) / len(precisions), 3) if precisions else None,
        "n": top_n,
        "baseRate": round(sum(test_labels) / len(test_labels), 3) if test_labels else None,
        "trainExamples": len(train),
        "holdoutExamples": len(test),
        "holdoutFrom": min(holdout_dates).isoformat(),
        "holdoutTo": max(holdout_dates).isoformat(),
    }
    usable = validation_auc is not None and validation_auc >= config.MIN_VALIDATION_AUC
    stamp = timezone.now().strftime("%Y%m%d%H%M%S%f")
    model = ChurnModel.objects.create(
        branch=branch, version=f"logreg-{branch.lower()}-{as_of:%Y%m%d}-{stamp}", trained_as_of=as_of,
        features=FEATURE_KEYS, coefficients=final["coefficients"], intercept=final["intercept"],
        means=final["means"], stds=final["stds"], metrics=metrics, examples=len(examples),
        cancellations=len(cancellations), members=len(members), usable=usable,
    )
    if not usable:
        return None, f"the model didn't validate well enough (AUC {metrics['auc']}, needs {config.MIN_VALIDATION_AUC})"
    return model, ""


def params_of(model):
    return {
        "coefficients": model.coefficients, "intercept": model.intercept, "means": model.means, "stds": model.stds,
    }
