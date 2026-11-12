from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.models import StaffAccount
from administration.permissions import authorize, get_staff_account
from audit.log import record
from audit.models import AuditLog
from notifications.models import StaffNotification

from . import pay
from .models import MAX_HOURLY, CoachPayRate

# User story: "As a coach, I want to view my completed session count and
# earnings for the current pay period, so that I can verify my pay is
# correct."
#
#   * The coach sees their own statement (/api/payroll/me), this month or any
#     of the last eleven: every session, the rate it was paid at, the total.
#   * Their branch manager sets their hourly rates and can open the same
#     statement, to answer "is my pay right?" from the same numbers.
#
# Who manages a coach's pay: manage_billing (Branch Manager, System
# Administrator) for coaches at their own branch; a coach who isn't tied to a
# branch, or one at another branch, needs view_all_branches too. A rate can't
# be back-dated into a pay period that has already ended, so a closed month's
# pay never changes after the fact. Every change is audited and the coach is
# notified.

MANAGE = "manage_billing"
ALL_BRANCHES = "view_all_branches"
HOURLY = {"max_digits": 6, "decimal_places": 2, "min_value": Decimal("0"), "max_value": Decimal(MAX_HOURLY)}


def _is_coach(account):
    return account.job_title == StaffAccount.JobTitle.COACH


def _may_manage(account, coach):
    permissions = account.role.permissions
    if MANAGE not in permissions:
        return False
    return ALL_BRANCHES in permissions or (bool(coach.branch) and coach.branch == account.branch)


def _statement(coach, request):
    start, end, error = pay.parse_period(request.query_params.get("period"))
    if error:
        return Response({"error": {"period": [error]}}, status=400)
    return Response(pay.statement(coach, start, end))


# GET /api/payroll/me?period=YYYY-MM - the signed-in coach's own statement.
@api_view(["GET"])
def my_pay(request):
    account = get_staff_account(request)
    if account is None:
        return Response({"error": "Not authenticated."}, status=401)
    if not _is_coach(account):
        return Response({"error": "Only coaches have a session pay statement."}, status=403)
    return _statement(account, request)


def _managed_coach(request, coach_id):
    account, denied = authorize(request, MANAGE)
    if denied:
        return None, None, denied
    coach = StaffAccount.objects.filter(id=coach_id, job_title=StaffAccount.JobTitle.COACH).first()
    if coach is None:
        return None, None, Response({"error": f"Coach {coach_id} not found."}, status=404)
    if not _may_manage(account, coach):
        return None, None, Response({"error": "You can only manage the pay of coaches at your own branch."}, status=403)
    return account, coach, None


# GET /api/payroll/coaches?period=YYYY-MM - the coaches this account manages,
# each with their current rate, any scheduled change, and the period's totals.
@api_view(["GET"])
def coach_list(request):
    account, denied = authorize(request, MANAGE)
    if denied:
        return denied
    start, end, error = pay.parse_period(request.query_params.get("period"))
    if error:
        return Response({"error": {"period": [error]}}, status=400)
    coaches = StaffAccount.objects.filter(job_title=StaffAccount.JobTitle.COACH).order_by("-is_active", "full_name")
    results = []
    for coach in coaches:
        if not _may_manage(account, coach):
            continue
        statement = pay.statement(coach, start, end)
        results.append({
            "id": coach.id, "name": coach.full_name, "branch": coach.branch, "active": coach.is_active,
            "currentRate": statement["rates"]["current"], "scheduled": statement["rates"]["scheduled"],
            "summary": statement["summary"],
        })
    today = timezone.localdate()
    return Response({
        "period": {"key": pay.period_key(start), "label": f"{start:%B %Y}"},
        "periods": pay.available_periods(today),
        "earliestEffectiveFrom": pay.parse_period(None, today)[0],
        "maxHourly": str(MAX_HOURLY),
        "results": results,
    })


# GET /api/payroll/coaches/<id>?period=YYYY-MM - that coach's statement, plus
# their whole rate history.
@api_view(["GET"])
def coach_detail(request, coach_id):
    _, coach, denied = _managed_coach(request, coach_id)
    if denied:
        return denied
    response = _statement(coach, request)
    if response.status_code == 200:
        response.data["rateHistory"] = [pay.rate_payload(r) for r in pay.rates_for(coach)[::-1]]
    return response


class RateSerializer(serializers.Serializer):
    classHourly = serializers.DecimalField(**HOURLY)
    ptHourly = serializers.DecimalField(**HOURLY)
    effectiveFrom = serializers.DateField()
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, trim_whitespace=True)

    def validate_effectiveFrom(self, value):
        today = timezone.localdate()
        first_open_day = pay.parse_period(None, today)[0]
        if value < first_open_day:
            raise serializers.ValidationError(
                f"Pay for periods that have ended can't change - pick {first_open_day:%d %b %Y} or later.",
            )
        if value > today + timedelta(days=365):
            raise serializers.ValidationError("That's more than a year ahead.")
        return value


def _notify(coach, title, message):
    StaffNotification.objects.create(
        recipient=coach, kind=StaffNotification.Kind.PAY_RATE_CHANGED, branch=coach.branch or "", title=title,
        message=message,
    )


def _rate_words(class_hourly, pt_hourly):
    return f"${pay.money(class_hourly)}/hour for classes and ${pay.money(pt_hourly)}/hour for private training"


# POST /api/payroll/coaches/<id>/rates - Body: { classHourly, ptHourly,
# effectiveFrom, note? }. A rate on a date that already has one replaces it.
@api_view(["POST"])
def set_rate(request, coach_id):
    account, coach, denied = _managed_coach(request, coach_id)
    if denied:
        return denied
    if not coach.is_active:
        return Response({"error": "This coach's account is deactivated."}, status=409)
    serializer = RateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    with transaction.atomic():
        StaffAccount.objects.select_for_update().filter(pk=coach.pk).first()
        existing = CoachPayRate.objects.filter(coach=coach, effective_from=data["effectiveFrom"]).first()
        before = pay.rate_payload(existing)
        rate, created = CoachPayRate.objects.update_or_create(
            coach=coach, effective_from=data["effectiveFrom"],
            defaults={"class_hourly": data["classHourly"], "pt_hourly": data["ptHourly"],
                      "note": data.get("note", ""), "set_by": account},
        )
        after = pay.rate_payload(rate)
        when = "today" if rate.effective_from == timezone.localdate() else f"from {rate.effective_from:%d %b %Y}"
        record(
            request, AuditLog.Action.PAY_RATE_SET, actor=account, target=coach, branch=coach.branch or "",
            summary=f"Set {coach.full_name}'s pay to {_rate_words(rate.class_hourly, rate.pt_hourly)} {when}",
            details={"before": before, "after": after} if before else {"after": after},
        )
        _notify(coach, "Your pay rate was updated",
                f"{account.full_name} set your pay to {_rate_words(rate.class_hourly, rate.pt_hourly)} {when}. "
                "See My Pay for how it applies to your sessions.")
    return Response(pay.rate_payload(rate), status=201 if created else 200)


# DELETE /api/payroll/coaches/<id>/rates/<rate_id> - take back a rate change
# that hasn't taken effect yet. One already in use is corrected by setting a
# new rate on the same date instead.
@api_view(["DELETE"])
def remove_rate(request, coach_id, rate_id):
    account, coach, denied = _managed_coach(request, coach_id)
    if denied:
        return denied
    rate = CoachPayRate.objects.filter(id=rate_id, coach=coach).first()
    if rate is None:
        return Response({"error": "Rate not found."}, status=404)
    if rate.effective_from <= timezone.localdate():
        return Response({
            "error": "This rate is already in use. To correct it, set a new rate on the same date.",
        }, status=409)
    removed = pay.rate_payload(rate)
    rate.delete()
    record(
        request, AuditLog.Action.PAY_RATE_REMOVED, actor=account, target=coach, branch=coach.branch or "",
        summary=f"Removed {coach.full_name}'s pay change planned for {rate.effective_from:%d %b %Y}",
        details={"removed": removed},
    )
    _notify(coach, "A planned pay change was withdrawn",
            f"The change to {_rate_words(rate.class_hourly, rate.pt_hourly)} from {rate.effective_from:%d %b %Y} "
            "won't happen.")
    return Response(status=204)
