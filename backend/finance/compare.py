from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from billing.models import Payment
from members.models import Member
from retail.models import Sale

from .models import Expense
from .views import ALL_BRANCHES_PERMISSION, MAX_CUSTOM_RANGE_DAYS, REPORT_PERMISSION, _day_start, _parsed_date_range

# User story (SCRUM-105): "As a general manager, I want to compare branch
# revenue performance in a single view, so that I can identify branches
# underperforming financially."
#
# Every branch over one period, ranked by revenue, against the period before
# it, with the reasons a branch is flagged spelled out. Revenue is the same
# as the Financial Report: membership payments by the paying member's branch
# plus retail sales rung up there (voided ones excluded); expenses come from
# the Expense ledger.
#
# A branch is flagged "underperforming" for any of:
#   * a loss - expenses above revenue;
#   * revenue below LOW_SHARE of the average branch's revenue;
#   * revenue down DECLINE_PERCENT % or more on the previous period;
#   * revenue per active member below LOW_SHARE of the company figure
#     (a big branch can hide a weak one in raw totals; this evens that out).
# Active members are counted as of today - the member table has no history.

LOW_SHARE = Decimal("0.75")
DECLINE_PERCENT = 15
TREND_MONTHS = 6
PERIODS = ["this_month", "last_month", "this_quarter", "last_quarter", "this_year", "custom"]
CENT = Decimal("0.01")


def _money(value):
    return f"{value.quantize(CENT, rounding=ROUND_HALF_UP)}"


# For sentences: thousands separated, e.g. 7,456.50.
def _readable(value):
    return f"{value.quantize(CENT, rounding=ROUND_HALF_UP):,}"


def _percent(part, whole):
    if not whole:
        return None
    return float((Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _add_months(day, months):
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def _quarter_start(day):
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


# (period, date_from, date_to, previous_from, previous_to, error). A period
# still running (this month, quarter, year) is compared with the same stretch
# of the one before - 1-18 Nov against 1-18 Oct - so it's like for like.
def resolve_period(params, today):
    period = (params.get("period") or "this_month").strip()
    if period not in PERIODS:
        return (None,) * 5 + (Response({"error": f'Invalid period "{period}". Must be one of: {", ".join(PERIODS)}'}, status=400),)
    if period == "custom":
        if not params.get("dateFrom") or not params.get("dateTo"):
            return (None,) * 5 + (Response({"error": "A custom period needs both dateFrom and dateTo."}, status=400),)
        date_from, date_to, error = _parsed_date_range(params)
        if error:
            return (None,) * 5 + (error,)
        if (date_to - date_from).days >= MAX_CUSTOM_RANGE_DAYS:
            return (None,) * 5 + (Response({"error": f"A custom period can cover at most {MAX_CUSTOM_RANGE_DAYS} days."}, status=400),)
        length = date_to - date_from
        previous_to = date_from - timedelta(days=1)
        return period, date_from, date_to, previous_to - length, previous_to, None

    if period in ("this_month", "last_month"):
        start = today.replace(day=1) if period == "this_month" else _add_months(today.replace(day=1), -1)
        end = today if period == "this_month" else today.replace(day=1) - timedelta(days=1)
        step = 1
    elif period in ("this_quarter", "last_quarter"):
        start = _quarter_start(today) if period == "this_quarter" else _add_months(_quarter_start(today), -3)
        end = today if period == "this_quarter" else _quarter_start(today) - timedelta(days=1)
        step = 3
    else:
        start, end, step = date(today.year, 1, 1), today, 12
    previous_from = _add_months(start, -step)
    if end == today:
        previous_to = _add_months(end, -step)       # the same stretch, a period earlier
    else:
        previous_to = start - timedelta(days=1)     # the whole period before
    return period, start, end, previous_from, previous_to, None


def revenue_and_expenses(branches, date_from, date_to):
    start, end = _day_start(date_from), _day_start(date_to + timedelta(days=1))
    memberships, retail, expenses = defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    payments = Payment.objects.filter(member__branch__in=branches, paid_at__gte=start, paid_at__lt=end)
    for row in payments.values("member__branch").annotate(total=Sum("amount")):
        memberships[row["member__branch"]] = row["total"]
    sales = Sale.objects.filter(branch__in=branches, voided_at__isnull=True, sold_at__gte=start, sold_at__lt=end)
    for row in sales.values("branch").annotate(total=Sum("total")):
        retail[row["branch"]] = row["total"]
    spent = Expense.objects.filter(branch__in=branches, incurred_on__gte=date_from, incurred_on__lte=date_to)
    for row in spent.values("branch").annotate(total=Sum("amount")):
        expenses[row["branch"]] = row["total"]
    return {b: {"memberships": memberships[b], "retail": retail[b], "expenses": expenses[b]} for b in branches}


# Revenue per branch per calendar month, for the last TREND_MONTHS months up
# to the end of the period.
def monthly_trend(branches, date_to):
    last = date_to.replace(day=1)
    months = [_add_months(last, -n) for n in range(TREND_MONTHS - 1, -1, -1)]
    start, end = _day_start(months[0]), _day_start(_add_months(last, 1))
    totals = defaultdict(Decimal)
    payments = Payment.objects.filter(member__branch__in=branches, paid_at__gte=start, paid_at__lt=end)
    for row in payments.annotate(month=TruncMonth("paid_at")).values("member__branch", "month").annotate(total=Sum("amount")):
        totals[(row["member__branch"], row["month"].date() if hasattr(row["month"], "date") else row["month"])] += row["total"]
    sales = Sale.objects.filter(branch__in=branches, voided_at__isnull=True, sold_at__gte=start, sold_at__lt=end)
    for row in sales.annotate(month=TruncMonth("sold_at")).values("branch", "month").annotate(total=Sum("total")):
        totals[(row["branch"], row["month"].date() if hasattr(row["month"], "date") else row["month"])] += row["total"]
    return {
        "months": [m.strftime("%Y-%m") for m in months],
        "series": [{"branch": b, "revenue": [_money(totals[(b, m)]) for m in months]} for b in branches],
    }


def _flags(row, average_revenue, company_per_member):
    flags = []
    if row["net"] < 0:
        flags.append({"code": "loss", "text": f"Running at a loss of ${_readable(-row['net'])}"})
    if average_revenue and row["revenue"] < average_revenue * LOW_SHARE:
        flags.append({"code": "low_revenue",
                      "text": f"Revenue {(row['revenue'] * 100 / average_revenue).quantize(Decimal(1), rounding=ROUND_HALF_UP)}% of the branch average"})
    if row["growthPercent"] is not None and row["growthPercent"] <= -DECLINE_PERCENT:
        flags.append({"code": "declining", "text": f"Revenue down {abs(row['growthPercent']):.1f}% on the previous period"})
    if row["perMember"] is not None and company_per_member and row["perMember"] < company_per_member * LOW_SHARE:
        flags.append({"code": "low_per_member",
                      "text": f"${_readable(row['perMember'])} per active member vs ${_readable(company_per_member)} company-wide"})
    return flags


# GET /api/finance/compare?period=this_month|last_month|this_quarter|last_quarter|this_year|custom&dateFrom=&dateTo=
@api_view(["GET"])
def compare_branches(request):
    account, denied = authorize(request, REPORT_PERMISSION)
    if denied:
        return denied
    if ALL_BRANCHES_PERMISSION not in account.role.permissions:
        return Response({"error": "Comparing branches needs access to every branch."}, status=403)
    period, date_from, date_to, previous_from, previous_to, error = resolve_period(request.query_params, timezone.localdate())
    if error:
        return error

    branches = list(Member.Branch.values)
    now = revenue_and_expenses(branches, date_from, date_to)
    before = revenue_and_expenses(branches, previous_from, previous_to)
    active = defaultdict(int)
    for row in Member.objects.filter(status=Member.Status.ACTIVE).values("branch").annotate(n=Count("id")):
        active[row["branch"]] = row["n"]

    rows = []
    for b in branches:
        revenue = now[b]["memberships"] + now[b]["retail"]
        previous = before[b]["memberships"] + before[b]["retail"]
        rows.append({
            "branch": b, "revenue": revenue, "memberships": now[b]["memberships"], "retail": now[b]["retail"],
            "expenses": now[b]["expenses"], "net": revenue - now[b]["expenses"], "previousRevenue": previous,
            "growthPercent": _percent(revenue - previous, previous),
            "activeMembers": active[b], "perMember": revenue / active[b] if active[b] else None,
        })

    total_revenue = sum(r["revenue"] for r in rows)
    total_expenses = sum(r["expenses"] for r in rows)
    total_previous = sum(r["previousRevenue"] for r in rows)
    total_members = sum(r["activeMembers"] for r in rows)
    average_revenue = total_revenue / len(rows) if rows else Decimal("0")
    company_per_member = total_revenue / total_members if total_members else None

    rows.sort(key=lambda r: (-r["revenue"], r["branch"]))
    results = []
    for rank, r in enumerate(rows, start=1):
        flags = _flags(r, average_revenue, company_per_member)
        results.append({
            "branch": r["branch"],
            "rank": rank,
            "revenue": _money(r["revenue"]),
            "revenueBySource": {"memberships": _money(r["memberships"]), "retail": _money(r["retail"])},
            "expenses": _money(r["expenses"]),
            "net": _money(r["net"]),
            "marginPercent": _percent(r["net"], r["revenue"]),
            "sharePercent": _percent(r["revenue"], total_revenue),
            "previousRevenue": _money(r["previousRevenue"]),
            "growthPercent": r["growthPercent"],
            "activeMembers": r["activeMembers"],
            "revenuePerMember": None if r["perMember"] is None else _money(r["perMember"]),
            "flags": flags,
            "underperforming": bool(flags),
        })

    return Response({
        "period": period,
        "periods": PERIODS,
        "dateFrom": date_from,
        "dateTo": date_to,
        "previous": {"dateFrom": previous_from, "dateTo": previous_to},
        "rules": {"lowSharePercent": int(LOW_SHARE * 100), "declinePercent": DECLINE_PERCENT},
        "totals": {
            "revenue": _money(total_revenue),
            "expenses": _money(total_expenses),
            "net": _money(total_revenue - total_expenses),
            "marginPercent": _percent(total_revenue - total_expenses, total_revenue),
            "previousRevenue": _money(total_previous),
            "growthPercent": _percent(total_revenue - total_previous, total_previous),
            "averageRevenue": _money(average_revenue),
            "activeMembers": total_members,
            "revenuePerMember": None if company_per_member is None else _money(company_per_member),
        },
        "branches": results,
        "underperformingCount": sum(1 for r in results if r["underperforming"]),
        "trend": monthly_trend(branches, date_to),
    })
