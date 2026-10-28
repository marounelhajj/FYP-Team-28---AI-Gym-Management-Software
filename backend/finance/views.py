from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from billing.models import Payment
from headcount.views import resolve_branch
from members.models import Member
from retail.models import Sale

from .models import Expense
from .serializers import ExpenseSerializer, ExpenseWriteSerializer

REPORT_PERMISSION = "view_financial_reports"
MANAGE_PERMISSION = "manage_billing"
# Lets a role see every branch (General Manager, System Administrator).
# Without it, a role only ever sees its own staff account's branch - same
# key headcount.views.resolve_branch already uses for the same idea.
ALL_BRANCHES_PERMISSION = "view_all_branches"


def _day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _parse_date(value, name):
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, Response({"error": f'Invalid {name} "{value}". Use YYYY-MM-DD.'}, status=400)


# Which branches the caller may see financial data for. Same rule as
# headcount.views.resolve_branch (a Branch Manager only ever sees their
# own branch; view_all_branches sees any), but this report compares
# branches side by side by default, so it returns a list - every branch
# unless narrowed to one with ?branch=, not the single "current branch"
# headcount resolves to.
def resolve_branches(account, requested):
    all_branches = list(Member.Branch.values)
    requested = (requested or "").strip()
    if requested and requested not in all_branches:
        return None, Response(
            {"error": f'Invalid branch "{requested}". Must be one of: {", ".join(all_branches)}'}, status=400,
        )

    if ALL_BRANCHES_PERMISSION in account.role.permissions:
        return ([requested] if requested else all_branches), None

    if not account.branch:
        return None, Response(
            {"error": "Your account isn't assigned to a branch yet. Ask a System Administrator to set one."},
            status=403,
        )
    if requested and requested != account.branch:
        return None, Response({"error": "You can only see financial data for your own branch."}, status=403)
    return [account.branch], None


def _parsed_date_range(params):
    date_from = date_to = None
    if params.get("dateFrom"):
        date_from, error = _parse_date(params["dateFrom"], "dateFrom")
        if error:
            return None, None, error
    if params.get("dateTo"):
        date_to, error = _parse_date(params["dateTo"], "dateTo")
        if error:
            return None, None, error
    if date_from and date_to and date_from > date_to:
        return None, None, Response({"error": "dateFrom must be on or before dateTo."}, status=400)
    return date_from, date_to, None


# GET /api/finance/report?branch=&dateFrom=&dateTo=
#
# Revenue (the sum of billing.Payment.amount, grouped by the paying
# member's branch, plus retail sales at that branch - split out in
# "revenueBySource") and expenses (this app's own Expense model - see
# models.py for why that's the one new thing this story needed) for every
# branch the caller may see, plus the net (revenue - expenses) and an
# expense breakdown by category. Every branch the caller can see is
# always listed, even at zero, so a quiet branch is as visible as a busy
# one (same idea as audit.views.retention_report).
#
# 200 + {"dateFrom", "dateTo", "branches": [{"branch", "revenue", "revenueBySource",
#        "expenses", "net", "expensesByCategory"}, ...], "totals"}.
# Amounts are strings ("1234.56"), same convention as billing's
# PaymentSerializer, so they round-trip without float error.
#
# User story: "As a general manager, I want to view expense and revenue
# data for each branch, so that I can monitor financial performance and
# compare branches."
@api_view(["GET"])
def financial_report(request):
    account, denied = authorize(request, REPORT_PERMISSION)
    if denied:
        return denied

    branches, error = resolve_branches(account, request.query_params.get("branch"))
    if error:
        return error
    date_from, date_to, error = _parsed_date_range(request.query_params)
    if error:
        return error

    payments = Payment.objects.filter(member__branch__in=branches)
    if date_from:
        payments = payments.filter(paid_at__gte=_day_start(date_from))
    if date_to:
        payments = payments.filter(paid_at__lt=_day_start(date_to + timedelta(days=1)))

    expenses = Expense.objects.filter(branch__in=branches)
    if date_from:
        expenses = expenses.filter(incurred_on__gte=date_from)
    if date_to:
        expenses = expenses.filter(incurred_on__lte=date_to)

    # Retail (point of sale) counts too, at the branch the sale was rung up -
    # voided sales don't.
    sales = Sale.objects.filter(branch__in=branches, voided_at__isnull=True)
    if date_from:
        sales = sales.filter(sold_at__gte=_day_start(date_from))
    if date_to:
        sales = sales.filter(sold_at__lt=_day_start(date_to + timedelta(days=1)))

    membership_by_branch = defaultdict(lambda: Decimal("0"))
    for row in payments.values("member__branch").annotate(total=Sum("amount")):
        membership_by_branch[row["member__branch"]] = row["total"]
    retail_by_branch = defaultdict(lambda: Decimal("0"))
    for row in sales.values("branch").annotate(total=Sum("total")):
        retail_by_branch[row["branch"]] = row["total"]
    revenue_by_branch = {b: membership_by_branch[b] + retail_by_branch[b] for b in branches}

    expense_by_branch = defaultdict(lambda: Decimal("0"))
    category_by_branch = defaultdict(dict)
    for row in expenses.values("branch", "category").annotate(total=Sum("amount")):
        expense_by_branch[row["branch"]] += row["total"]
        category_by_branch[row["branch"]][row["category"]] = f"{row['total']:.2f}"

    results = []
    totals = {"revenue": Decimal("0"), "expenses": Decimal("0")}
    for branch in branches:
        revenue = revenue_by_branch[branch]
        branch_expenses = expense_by_branch[branch]
        results.append({
            "branch": branch,
            "revenue": f"{revenue:.2f}",
            "revenueBySource": {
                "memberships": f"{membership_by_branch[branch]:.2f}",
                "retail": f"{retail_by_branch[branch]:.2f}",
            },
            "expenses": f"{branch_expenses:.2f}",
            "net": f"{revenue - branch_expenses:.2f}",
            "expensesByCategory": category_by_branch[branch],
        })
        totals["revenue"] += revenue
        totals["expenses"] += branch_expenses

    return Response({
        "dateFrom": date_from, "dateTo": date_to,
        "branches": results,
        "totals": {
            "revenue": f"{totals['revenue']:.2f}",
            "expenses": f"{totals['expenses']:.2f}",
            "net": f"{totals['revenue'] - totals['expenses']:.2f}",
        },
    })


# GET  /api/finance/expenses?branch=&dateFrom=&dateTo=&limit=&offset= - list recorded expenses, newest first.
# POST /api/finance/expenses - record one.
#
# How the Expense rows behind the report above actually get there. Gated
# on manage_billing rather than view_financial_reports, same split as the
# rest of this app (e.g. manage_members vs view_financial_reports):
# reading the comparison report and entering a cost are different
# privileges, even though today's seeded roles happen to give both to
# System Administrator.
@api_view(["GET", "POST"])
def expense_list(request):
    account, denied = authorize(request, MANAGE_PERMISSION)
    if denied:
        return denied

    if request.method == "POST":
        serializer = ExpenseWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=400)
        data = serializer.validated_data
        if ALL_BRANCHES_PERMISSION not in account.role.permissions and account.branch and data["branch"] != account.branch:
            return Response({"error": "You can only record an expense for your own branch."}, status=403)
        expense = Expense.objects.create(recorded_by=account, **data)
        return Response(ExpenseSerializer(expense).data, status=201)

    branches, error = resolve_branches(account, request.query_params.get("branch"))
    if error:
        return error
    date_from, date_to, error = _parsed_date_range(request.query_params)
    if error:
        return error

    queryset = Expense.objects.filter(branch__in=branches).select_related("recorded_by")
    if date_from:
        queryset = queryset.filter(incurred_on__gte=date_from)
    if date_to:
        queryset = queryset.filter(incurred_on__lte=date_to)

    try:
        limit = int(request.query_params.get("limit", 50))
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 200))
    try:
        offset = max(0, int(request.query_params.get("offset", 0)))
    except ValueError:
        offset = 0

    total = queryset.count()
    page = queryset[offset : offset + limit]
    return Response({
        "total": total, "limit": limit, "offset": offset,
        "results": ExpenseSerializer(page, many=True).data,
    })


# GET /api/finance/meta - the category list and the branches the caller
# may file an expense for or see in the report, so neither the expense
# form nor the branch filter ever hardcodes a list that can drift from
# the backend.
@api_view(["GET"])
def finance_meta(request):
    account, denied = authorize(request, REPORT_PERMISSION, MANAGE_PERMISSION)
    if denied:
        return denied

    branches = (
        list(Member.Branch.values)
        if ALL_BRANCHES_PERMISSION in account.role.permissions
        else ([account.branch] if account.branch else [])
    )
    return Response({
        "branches": branches,
        "categories": [choice.value for choice in Expense.Category],
    })


# --- Branch Finances (SCRUM-26) -------------------------------------------

MAX_CUSTOM_RANGE_DAYS = 366
# Up to this many days the chart has one point per day; longer ranges are
# grouped by month so it stays readable.
DAILY_SERIES_MAX_DAYS = 62


def _period_dates(params, today):
    period = (params.get("period") or "this_month").strip()
    if period == "this_month":
        return period, today.replace(day=1), today, None
    if period == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return period, end.replace(day=1), end, None
    if period == "custom":
        if not params.get("dateFrom") or not params.get("dateTo"):
            return None, None, None, Response({"error": "A custom period needs both dateFrom and dateTo."}, status=400)
        date_from, date_to, error = _parsed_date_range(params)
        if error:
            return None, None, None, error
        if (date_to - date_from).days >= MAX_CUSTOM_RANGE_DAYS:
            return None, None, None, Response(
                {"error": f"A custom period can cover at most {MAX_CUSTOM_RANGE_DAYS} days."}, status=400,
            )
        return period, date_from, date_to, None
    return None, None, None, Response(
        {"error": f'Invalid period "{period}". Must be one of: this_month, last_month, custom'}, status=400,
    )


def _series_keys(date_from, date_to):
    if (date_to - date_from).days < DAILY_SERIES_MAX_DAYS:
        keys = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
        return "day", keys, lambda d: d.isoformat()
    keys, cursor = [], date_from.replace(day=1)
    while cursor <= date_to:
        keys.append(cursor)
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return "month", keys, lambda d: d.strftime("%Y-%m")


# GET /api/finance/branch?branch=&period=this_month|last_month|custom&dateFrom=&dateTo=
#
# One branch's revenue, expenses and net over a period (this month by
# default), for the Branch Finances page. Same branch rule as live headcount
# (SCRUM-127, headcount.views.resolve_branch): a Branch Manager only ever
# gets their own branch (another one is a 403), a role with view_all_branches
# (General Manager, System Administrator) may ask for any, defaulting to their
# own branch or the first one.
#
# Revenue is split by source: first payments at signup/registration,
# renewals (incl. reactivations) and retail sales (voided ones excluded).
# "series" is revenue vs expenses per day, or per month for ranges longer
# than DAILY_SERIES_MAX_DAYS days. Amounts are strings, as in /report.
@api_view(["GET"])
def branch_finances(request):
    account, denied = authorize(request, REPORT_PERMISSION)
    if denied:
        return denied

    branch, branches, error = resolve_branch(account, request.query_params.get("branch"), subject="finances")
    if error:
        return error
    period, date_from, date_to, error = _period_dates(request.query_params, timezone.localdate())
    if error:
        return error

    start, end = _day_start(date_from), _day_start(date_to + timedelta(days=1))
    granularity, keys, label = _series_keys(date_from, date_to)

    def bucket(day):
        return label(day if granularity == "day" else day.replace(day=1))

    series = {label(k): {"revenue": Decimal("0"), "expenses": Decimal("0")} for k in keys}
    sources = {"firstPayments": Decimal("0"), "renewals": Decimal("0"), "retail": Decimal("0")}
    categories = defaultdict(lambda: Decimal("0"))

    payments = Payment.objects.filter(member__branch=branch, paid_at__gte=start, paid_at__lt=end)
    for paid_at, amount, note in payments.values_list("paid_at", "amount", "note"):
        sources["firstPayments" if note.startswith("First payment") else "renewals"] += amount
        series[bucket(timezone.localtime(paid_at).date())]["revenue"] += amount

    sales = Sale.objects.filter(branch=branch, voided_at__isnull=True, sold_at__gte=start, sold_at__lt=end)
    for sold_at, total in sales.values_list("sold_at", "total"):
        sources["retail"] += total
        series[bucket(timezone.localtime(sold_at).date())]["revenue"] += total

    expenses = Expense.objects.filter(branch=branch, incurred_on__gte=date_from, incurred_on__lte=date_to)
    for incurred_on, category, amount in expenses.values_list("incurred_on", "category", "amount"):
        categories[category] += amount
        series[bucket(incurred_on)]["expenses"] += amount

    revenue, total_expenses = sum(sources.values()), sum(categories.values())
    return Response({
        "branch": branch,
        "branches": branches,
        "canChooseBranch": len(branches) > 1,
        "canManageExpenses": MANAGE_PERMISSION in account.role.permissions,
        "period": period,
        "dateFrom": date_from,
        "dateTo": date_to,
        "revenue": f"{revenue:.2f}",
        "revenueBySource": {name: f"{amount:.2f}" for name, amount in sources.items()},
        "expenses": f"{total_expenses:.2f}",
        "expensesByCategory": {name: f"{amount:.2f}" for name, amount in categories.items()},
        "net": f"{revenue - total_expenses:.2f}",
        "granularity": granularity,
        "series": [
            {"date": key, "revenue": f"{values['revenue']:.2f}", "expenses": f"{values['expenses']:.2f}"}
            for key, values in series.items()
        ],
    })


# PATCH  /api/finance/expenses/<id> - edit an expense (any subset of branch,
#        category, amount, incurredOn, note).
# DELETE /api/finance/expenses/<id> - remove it.
#
# Gated on manage_billing like recording one. A caller without
# view_all_branches only reaches expenses of their own branch: another
# branch's expense is a 404 (its existence isn't confirmed), and moving one
# to another branch is a 403.
@api_view(["PATCH", "DELETE"])
def expense_detail(request, expense_id):
    account, denied = authorize(request, MANAGE_PERMISSION)
    if denied:
        return denied

    sees_all = ALL_BRANCHES_PERMISSION in account.role.permissions
    expense = Expense.objects.filter(pk=expense_id).select_related("recorded_by").first()
    if expense is None or (not sees_all and expense.branch != account.branch):
        return Response({"error": "Expense not found."}, status=404)

    if request.method == "DELETE":
        expense.delete()
        return Response(status=204)

    serializer = ExpenseWriteSerializer(data=request.data, partial=True)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    if not sees_all and data.get("branch", expense.branch) != account.branch:
        return Response({"error": "You can only keep an expense on your own branch."}, status=403)
    for field, value in data.items():
        setattr(expense, field, value)
    expense.save()
    return Response(ExpenseSerializer(expense).data)
