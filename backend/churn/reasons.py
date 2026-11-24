from datetime import date

# Plain-language reasons for the at-risk list (SCRUM-119).
#
# User story: "As a branch manager, I want each at-risk member to show the
# two or three reasons behind their ranking, so that staff know what to
# talk about on the call."
#
# The scoring (scoring.py) picks each member's top contributing features:
# the largest weighted terms of the rule-based score, or the largest
# coefficient x value pushes of the learned model. Here each one becomes a
# sentence with the member's real numbers, plus one short line staff can
# use on the call. Staff never see a score breakdown or a feature name.


def _date(iso, as_of):
    day = date.fromisoformat(iso) if isinstance(iso, str) else iso
    text = f"{day.day} {day:%b}"
    return text if day.year == as_of.year else f"{text} {day.year}"


def _rate(value):
    value = round(float(value), 1)
    return str(int(value)) if value == int(value) else f"{value:g}"


def _per_week(value):
    if float(value) == 0:
        return "none"
    return f"{_rate(value)} a week"


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _ago(days):
    if days < 14:
        return _plural(days, "day")
    if days < 70:
        return _plural(round(days / 7), "week")
    return _plural(round(days / 30), "month")


def attendance_drop(f, as_of):
    before, now = f["prior_per_week"], f["recent_per_week"]
    if float(now) == 0:
        text = f"Visits dropped from {_per_week(before)} to none in the last 4 weeks"
    else:
        text = f"Visits dropped from {_per_week(before)} to {_per_week(now)}"
    return text, "Ask how their routine is going and offer to book a class or session at a time that suits them."


def inactivity(f, as_of):
    days = f.get("days_since_last_visit")
    if days is None:
        return ("Hasn't checked in once since joining",
                "Ask what's stopped them getting started and offer a free intro session with a coach.")
    last = _date(f["last_visit"], as_of)
    return (f"Hasn't visited in {_plural(days, 'day')} (last visit {last})",
            "Check in personally and ask if anything is keeping them away.")


def no_shows(f, as_of):
    n = f["no_shows"]
    classes = "1 booked class or session" if n == 1 else f"{n} booked classes or sessions"
    return (f"Missed {classes} in the last 30 days",
            "Ask whether the class times still work for them and suggest another slot.")


def payment(f, as_of):
    if f.get("lapsed"):
        if f.get("lapsed_since"):
            text = f"Membership payment overdue since {_date(f['lapsed_since'], as_of)}"
        else:
            text = "No paid membership on file"
        return text, "Remind them gently that the renewal is due and offer to take payment at the desk or over the phone."
    days = f.get("last_late_days")
    when = _date(f["last_late_payment"], as_of) if f.get("last_late_payment") else None
    late = f.get("late_payments", 0)
    text = f"Last renewal was paid {_plural(days, 'day')} late, on {when}" if days and when else "Renewals paid late"
    if late > 1:
        text += f" ({late} late payments in 6 months)"
    return text, "If cost is a concern, mention the plan options, such as paying yearly."


def freeze(f, as_of):
    since = _date(f["last_freeze"], as_of) if f.get("last_freeze") else None
    if f.get("freeze_active"):
        text = f"Membership frozen since {since}" if since else "Membership is frozen"
        return text, "Ask when they plan to come back and whether you can help them restart."
    count = f.get("past_freezes", 0)
    text = f"Froze their membership on {since}" if since else "Froze their membership recently"
    if count > 1:
        text += f" ({count} freezes in 6 months)"
    return text, "Ask how things are going since the break and whether their schedule has settled."


def new_member(f, as_of):
    return (f"Joined {_ago(f['tenure_days'])} ago",
            "Welcome them, ask how their first weeks have gone, and offer a session with a coach.")


def renewal_soon(f, as_of):
    days = f.get("days_to_renewal")
    ends = _date(f["membership_ends"], as_of) if f.get("membership_ends") else None
    if days == 0:
        text = "Membership ends today"
    else:
        text = f"Membership ends in {_plural(days, 'day')} ({ends})"
    return text, "Remind them of the renewal date and ask if they'd like to renew now."


DESCRIBE = {
    "attendance_drop": attendance_drop,
    "inactivity": inactivity,
    "no_shows": no_shows,
    "payment": payment,
    "freeze": freeze,
    "new_member": new_member,
    "renewal_soon": renewal_soon,
}


# [{"feature", "points"}, ...] + the member's features ->
# [{"text", "talkingPoint"}, ...] in the same order.
def explain(reasons, features, as_of):
    out = []
    for reason in reasons:
        describe = DESCRIBE.get(reason["feature"])
        if describe is None:
            continue
        try:
            text, talking_point = describe(features, as_of)
        except (KeyError, TypeError, ValueError):
            # Features from an older snapshot without the numbers a sentence needs.
            continue
        out.append({"text": text, "talkingPoint": talking_point})
    return out

