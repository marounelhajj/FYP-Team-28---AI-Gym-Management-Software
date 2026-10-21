from datetime import date, datetime, time, timedelta

from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from members.models import Member

from .models import TrainingEvent
from .serializers import TrainingEventSerializer

VIEW_PERMISSION = "view_training_data"


def _parse_date(value, name):
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, Response({"error": f'Invalid {name} "{value}". Use YYYY-MM-DD.'}, status=400)


def _day_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


# GET /api/training-events
#
# Query params (all optional, all combinable):
#   eventType - check_in | cancellation | no_show | trainer_accept | trainer_reject
#   branch    - exact match: Hamra | Achrafieh | Jnah | Zalka
#   memberId  - one member's events
#   dateFrom  - YYYY-MM-DD, inclusive
#   dateTo    - YYYY-MM-DD, inclusive
#   limit     - page size (default 100, max 500)
#   offset    - pagination offset (default 0)
#
# Newest first. 200 + {"total", "limit", "offset", "results"}.
# Needs view_training_data (System Administrator).
#
# User story (SCRUM-73): "As a system administrator, I want check-ins,
# cancellations, no-shows, and trainer accept/reject decisions logged as
# training data from first release, so that the models have a dataset to
# learn from later."
@api_view(["GET"])
def training_event_list(request):
    _, denied = authorize(request, VIEW_PERMISSION)
    if denied:
        return denied

    params = request.query_params
    queryset = TrainingEvent.objects.all()

    event_type = (params.get("eventType") or "").strip()
    if event_type:
        if event_type not in TrainingEvent.EventType.values:
            return Response(
                {"error": f'Invalid eventType "{event_type}". Must be one of: {", ".join(TrainingEvent.EventType.values)}'},
                status=400,
            )
        queryset = queryset.filter(event_type=event_type)

    branch = (params.get("branch") or "").strip()
    if branch:
        if branch not in Member.Branch.values:
            return Response(
                {"error": f'Invalid branch "{branch}". Must be one of: {", ".join(Member.Branch.values)}'}, status=400,
            )
        queryset = queryset.filter(branch=branch)

    member_id = (params.get("memberId") or "").strip()
    if member_id:
        if not member_id.isdigit():
            return Response({"error": "memberId must be a number."}, status=400)
        queryset = queryset.filter(member_id=int(member_id))

    date_from = date_to = None
    if params.get("dateFrom"):
        date_from, error = _parse_date(params["dateFrom"], "dateFrom")
        if error:
            return error
        queryset = queryset.filter(occurred_at__gte=_day_start(date_from))
    if params.get("dateTo"):
        date_to, error = _parse_date(params["dateTo"], "dateTo")
        if error:
            return error
        queryset = queryset.filter(occurred_at__lt=_day_start(date_to + timedelta(days=1)))
    if date_from and date_to and date_from > date_to:
        return Response({"error": "dateFrom must be on or before dateTo."}, status=400)

    try:
        limit = int(params.get("limit", 100))
    except ValueError:
        limit = 100
    limit = max(1, min(limit, 500))
    try:
        offset = max(0, int(params.get("offset", 0)))
    except ValueError:
        offset = 0

    total = queryset.count()
    page = queryset[offset : offset + limit]
    return Response({
        "total": total, "limit": limit, "offset": offset,
        "results": TrainingEventSerializer(page, many=True).data,
    })
