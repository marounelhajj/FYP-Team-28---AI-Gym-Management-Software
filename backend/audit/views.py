from datetime import date, datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from members.models import Member

from .models import AuditLog
from .serializers import AuditLogSerializer

VIEW_PERMISSION = "view_audit_log"


# "staff.login_failed" -> "staff". Lets the filter pick a whole group
# ("everything about staff accounts") as well as one exact action.
def _category(action):
    return action.split(".", 1)[0]


CATEGORY_LABELS = {
    "staff": "Staff accounts & sign-in",
    "role": "Roles",
    "plan": "Membership plans",
    "promotion": "Branch promotions",
    "member": "Members",
    "payment": "Payments",
    "payment_method": "Payment methods",
    "access_card": "Access cards",
}


def _parse_date(value, name):
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, Response({"error": f'Invalid {name} "{value}". Use YYYY-MM-DD.'}, status=400)


# Start of a local calendar day as an aware datetime, so "from 2026-10-20"
# means midnight at the gym, not midnight UTC.
def _day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


# GET /api/audit-log
#
# Query params (all optional, all combinable):
#   user      - case-insensitive substring of the actor's username or name
#               (also matches the username typed in a failed sign-in)
#   action    - one exact action ("plan.updated") or a whole category ("plan")
#   branch    - exact match: Hamra | Achrafieh | Jnah | Zalka
#   dateFrom  - YYYY-MM-DD, inclusive
#   dateTo    - YYYY-MM-DD, inclusive
#   limit     - page size (default 50, max 200)
#   offset    - pagination offset (default 0)
#
# Newest first. 200 + {"total", "limit", "offset", "results"}.
#
# User story (SCRUM-125): "As a general manager, I want to search and
# filter the audit log by user, action type, branch and date range, so
# that I can investigate a specific incident."
@api_view(["GET"])
def audit_log_list(request):
    _, denied = authorize(request, VIEW_PERMISSION)
    if denied:
        return denied

    queryset, error = filtered_entries(request.query_params)
    if error:
        return error

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
        "results": AuditLogSerializer(page, many=True).data,
    })


# Applies the filters above; returns (queryset, None) or (None, 400 response).
# Shared with the CSV export so it exports exactly what's on screen.
def filtered_entries(params):
    queryset = AuditLog.objects.all()

    user = (params.get("user") or "").strip()
    if user:
        queryset = queryset.filter(Q(actor_username__icontains=user) | Q(actor_name__icontains=user))

    action = (params.get("action") or "").strip()
    if action:
        valid_actions = {choice.value for choice in AuditLog.Action}
        valid_categories = {_category(a) for a in valid_actions}
        if action in valid_actions:
            queryset = queryset.filter(action=action)
        elif action in valid_categories:
            queryset = queryset.filter(action__startswith=f"{action}.")
        else:
            return None, Response({"error": f'Invalid action "{action}".'}, status=400)

    branch = (params.get("branch") or "").strip()
    if branch:
        valid_branches = [choice.value for choice in Member.Branch]
        if branch not in valid_branches:
            return None, Response(
                {"error": f'Invalid branch "{branch}". Must be one of: {", ".join(valid_branches)}'}, status=400,
            )
        queryset = queryset.filter(branch=branch)

    date_from = date_to = None
    if params.get("dateFrom"):
        date_from, error = _parse_date(params["dateFrom"], "dateFrom")
        if error:
            return None, error
        queryset = queryset.filter(created_at__gte=_day_start(date_from))
    if params.get("dateTo"):
        date_to, error = _parse_date(params["dateTo"], "dateTo")
        if error:
            return None, error
        queryset = queryset.filter(created_at__lt=_day_start(date_to + timedelta(days=1)))
    if date_from and date_to and date_from > date_to:
        return None, Response({"error": "dateFrom must be on or before dateTo."}, status=400)

    return queryset, None


# GET /api/audit-log/meta
# Everything the filter bar needs, so it never hardcodes lists that can
# drift from the backend: the action types (grouped by category), the
# branches, and every user who appears in the log (for the user picker).
@api_view(["GET"])
def audit_log_meta(request):
    _, denied = authorize(request, VIEW_PERMISSION)
    if denied:
        return denied

    categories = {}
    for choice in AuditLog.Action:
        key = _category(choice.value)
        label = CATEGORY_LABELS.get(key, key)
        group = categories.setdefault(label, {"label": label, "value": key, "actions": []})
        group["actions"].append({"value": choice.value, "label": choice.label})

    users = (
        AuditLog.objects.exclude(actor_username="")
        .values("actor_username", "actor_name", "actor_role")
        .order_by("actor_username")
        .distinct()
    )
    seen = {}
    for row in users:
        # One entry per username, even if their name or role changed over time.
        seen.setdefault(row["actor_username"], {
            "username": row["actor_username"], "name": row["actor_name"], "role": row["actor_role"],
        })

    return Response({
        "actionGroups": list(categories.values()),
        "branches": [choice.value for choice in Member.Branch],
        "users": list(seen.values()),
    })
