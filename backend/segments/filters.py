from members.models import Member

# Segment filters (SCRUM-43). Every filter that is set must match (AND).
#
#   branches            ["Hamra", ...]
#   statuses            ["Active", "Frozen", "Cancelled"]   default: Active + Frozen
#   plans               ["Premium", ...]
#   ageMin / ageMax     years; members with no date of birth never match
#   tenureMonthsMin/Max months since they joined
#   visitsPerWeekMin/Max  average over the last 4 weeks
#   daysSinceLastVisitMin/Max  a member who never visited matches a Min, never a Max
#   classTypes          attended at least one of these in the last 90 days
#   ptClient            true = had a PT session in the last 90 days, false = didn't
#   riskLevels          ["High", "Medium", "Low"] from the latest churn score
#   renewalInDaysMin/Max  days until the membership ends (negative = already lapsed)
#   clusterGroup        id of a suggested-segment group (saved clusters)
#
# There is no gender on the member record, so there is no gender filter.

DEFAULT_STATUSES = [Member.Status.ACTIVE, Member.Status.FROZEN]
RISK_LEVELS = ["High", "Medium", "Low"]

LIST_FILTERS = ("branches", "statuses", "plans", "classTypes", "riskLevels")
RANGES = {
    "age": ("ageMin", "ageMax", 0, 120, False),
    "tenureMonths": ("tenureMonthsMin", "tenureMonthsMax", 0, 600, False),
    "visitsPerWeek": ("visitsPerWeekMin", "visitsPerWeekMax", 0, 14, True),
    "daysSinceLastVisit": ("daysSinceLastVisitMin", "daysSinceLastVisitMax", 0, 3650, False),
    "renewalInDays": ("renewalInDaysMin", "renewalInDaysMax", -3650, 3650, False),
}


class FilterError(ValueError):
    pass


def _number(key, value, low, high, decimal):
    if isinstance(value, bool):
        raise FilterError(f"{key} must be a number.")
    try:
        number = float(value) if decimal else int(value)
    except (TypeError, ValueError):
        raise FilterError(f"{key} must be a {'number' if decimal else 'whole number'}.")
    if decimal and float(number) != float(value):
        raise FilterError(f"{key} must be a number.")
    if not decimal and float(value) != int(value):
        raise FilterError(f"{key} must be a whole number.")
    if not low <= number <= high:
        raise FilterError(f"{key} must be between {low} and {high}.")
    return round(number, 2) if decimal else number


def clean_filters(raw):
    """Validates and normalises a filters object. Raises FilterError."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise FilterError("filters must be an object.")
    known = set(LIST_FILTERS) | {k for lo, hi, *_ in RANGES.values() for k in (lo, hi)} | {"ptClient", "clusterGroup"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise FilterError(f"Unknown filter: {', '.join(unknown)}.")

    out = {}
    allowed = {
        "branches": set(Member.Branch.values),
        "statuses": set(Member.Status.values),
        "riskLevels": set(RISK_LEVELS),
    }
    for key in LIST_FILTERS:
        value = raw.get(key)
        if value in (None, []):
            continue
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            raise FilterError(f"{key} must be a list of names.")
        value = sorted({v.strip() for v in value})
        if key in allowed:
            bad = [v for v in value if v not in allowed[key]]
            if bad:
                raise FilterError(f"Invalid {key}: {', '.join(bad)}.")
        out[key] = value

    for name, (lo_key, hi_key, low, high, decimal) in RANGES.items():
        lo = raw.get(lo_key)
        hi = raw.get(hi_key)
        lo = None if lo in (None, "") else _number(lo_key, lo, low, high, decimal)
        hi = None if hi in (None, "") else _number(hi_key, hi, low, high, decimal)
        if lo is not None and hi is not None and lo > hi:
            raise FilterError(f"{lo_key} can't be more than {hi_key}.")
        if lo is not None:
            out[lo_key] = lo
        if hi is not None:
            out[hi_key] = hi

    pt = raw.get("ptClient")
    if pt is not None:
        if not isinstance(pt, bool):
            raise FilterError("ptClient must be true, false or null.")
        out["ptClient"] = pt

    group = raw.get("clusterGroup")
    if group is not None:
        if isinstance(group, bool) or not isinstance(group, int):
            raise FilterError("clusterGroup must be a suggested segment id.")
        from .models import ClusterGroup
        if not ClusterGroup.objects.filter(pk=group).exists():
            raise FilterError("That suggested segment no longer exists.")
        out["clusterGroup"] = group
    return out


def _in_range(value, lo, hi):
    if lo is None and hi is None:
        return True
    if value is None:
        return False
    return (lo is None or value >= lo) and (hi is None or value <= hi)


def matches(profile, filters, today, cluster_members=None):
    f = filters
    if profile.status not in f.get("statuses", DEFAULT_STATUSES):
        return False
    if "branches" in f and profile.branch not in f["branches"]:
        return False
    if "plans" in f and profile.plan not in f["plans"]:
        return False
    if not _in_range(profile.age(today), f.get("ageMin"), f.get("ageMax")):
        return False
    if not _in_range(profile.tenure_months(today), f.get("tenureMonthsMin"), f.get("tenureMonthsMax")):
        return False
    if not _in_range(profile.visits_per_week(), f.get("visitsPerWeekMin"), f.get("visitsPerWeekMax")):
        return False
    days = profile.days_since_last_visit(today)
    lo, hi = f.get("daysSinceLastVisitMin"), f.get("daysSinceLastVisitMax")
    if days is None:
        # Never visited: as long ago as it gets.
        if hi is not None:
            return False
    elif not _in_range(days, lo, hi):
        return False
    if "classTypes" in f and not (profile.class_types & set(f["classTypes"])):
        return False
    if "ptClient" in f and profile.pt_client != f["ptClient"]:
        return False
    if "riskLevels" in f and profile.risk_level not in f["riskLevels"]:
        return False
    if not _in_range(profile.renewal_in_days(today), f.get("renewalInDaysMin"), f.get("renewalInDaysMax")):
        return False
    if "clusterGroup" in f and (cluster_members is None or profile.id not in cluster_members):
        return False
    return True


def cluster_members_for(filters):
    group_id = filters.get("clusterGroup")
    if group_id is None:
        return None
    from .models import ClusterGroup
    group = ClusterGroup.objects.filter(pk=group_id).first()
    return set(group.member_ids) if group else set()


def apply(profiles, filters, today):
    cluster = cluster_members_for(filters)
    return [p for p in profiles.values() if matches(p, filters, today, cluster)]


def describe(filters):
    """Plain-language summary, e.g. "Active, Hamra, visits 2+ a week"."""
    f = filters
    parts = [", ".join(f.get("statuses", DEFAULT_STATUSES))]
    if "branches" in f:
        parts.append(", ".join(f["branches"]))
    if "plans" in f:
        parts.append(" or ".join(f["plans"]) + " plan")

    def rng(label, lo, hi, unit=""):
        if lo is not None and hi is not None:
            return f"{label} {lo}-{hi}{unit}"
        if lo is not None:
            return f"{label} {lo}+{unit}"
        if hi is not None:
            return f"{label} up to {hi}{unit}"
        return None

    for text in (
        rng("age", f.get("ageMin"), f.get("ageMax")),
        rng("member for", f.get("tenureMonthsMin"), f.get("tenureMonthsMax"), " months"),
        rng("visits", f.get("visitsPerWeekMin"), f.get("visitsPerWeekMax"), " a week"),
        rng("last visit", f.get("daysSinceLastVisitMin"), f.get("daysSinceLastVisitMax"), " days ago"),
        rng("renews in", f.get("renewalInDaysMin"), f.get("renewalInDaysMax"), " days"),
    ):
        if text:
            parts.append(text)
    if "classTypes" in f:
        parts.append("attends " + " or ".join(f["classTypes"]))
    if "ptClient" in f:
        parts.append("PT client" if f["ptClient"] else "not a PT client")
    if "riskLevels" in f:
        parts.append(" or ".join(f["riskLevels"]).lower() + " churn risk")
    if "clusterGroup" in f:
        parts.append("from a suggested segment")
    return "; ".join(parts)
