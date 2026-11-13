from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import authorize
from audit.log import record
from audit.models import AuditLog
from headcount.views import resolve_branch
from members.models import Member
from notifications.delivery import notify_member
from notifications.models import MemberNotification, StaffNotification
from payroll.pay import available_periods, parse_period, period_key

from . import rules
from .models import AREAS, BranchSurvey, Complaint, ComplaintMessage
from .rules import ALL_BRANCHES, MANAGE
from .serializers import ComplaintSerializer, MessageSerializer, StatusSerializer, SurveySerializer

# User story: "As a branch manager, I want to view member feedback and
# complaints specific to my branch, so that I can address local service
# issues directly rather than waiting on a company wide report."
#
# Members:   /api/members/me/branch-feedback (surveys) and /api/members/me/complaints.
# Managers:  /api/branch-feedback/summary and /api/branch-feedback/complaints.
#
# A Branch Manager sees and answers only their own branch; a role with
# view_all_branches (General Manager, System Administrator) picks any - the
# company-wide view. Rules and numbers are in branchfeedback/rules.py.

SUBJECT = "member feedback"
TREND_MONTHS = 6


def _member(request):
    member_id = request.session.get("member_id")
    member = Member.objects.filter(id=member_id).first() if member_id else None
    if member is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    return member, None


def _choices(enum):
    return [{"value": v, "label": label} for v, label in enum.choices]


def _member_payload(member):
    complaints = member.complaints.prefetch_related("messages__author_staff", "messages__author_member")
    return {
        "homeBranch": member.branch,
        "surveys": rules.survey_status(member),
        "surveyEveryDays": rules.SURVEY_EVERY_DAYS,
        "visitDays": rules.VISIT_DAYS,
        "areas": [{"key": k, "label": label} for k, label in AREAS],
        "complaintBranches": rules.complaint_branches(member),
        "categories": _choices(Complaint.Category),
        "complaints": [rules.complaint_payload(c, for_staff=False) for c in complaints],
        "maxUnresolved": rules.MAX_UNRESOLVED,
        "responseHours": rules.RESPONSE_HOURS,
    }


# GET /api/members/me/branch-feedback - what the member can rate, and their complaints.
@api_view(["GET"])
def my_branch_feedback(request):
    member, denied = _member(request)
    if denied:
        return denied
    return Response(_member_payload(member))


# POST /api/members/me/branch-feedback/surveys - Body: { branch, nps (0-10),
# cleanliness?, equipment?, staff?, classes?, atmosphere? (1-5), comment?, anonymous? }
@api_view(["POST"])
def submit_survey(request):
    member, denied = _member(request)
    if denied:
        return denied
    serializer = SurveySerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    with transaction.atomic():
        # Locked, so a double tap can't slip two surveys past the monthly limit.
        Member.objects.select_for_update().get(pk=member.pk)
        problem = rules.survey_problem(member, data["branch"])
        if problem:
            return Response({"error": problem[1]}, status=problem[0])
        BranchSurvey.objects.create(member=member, **data)
    return Response(_member_payload(member), status=201)


def _notify_staff(complaint, title, message):
    StaffNotification.objects.bulk_create(
        StaffNotification(recipient=account, kind=StaffNotification.Kind.NEW_COMPLAINT, branch=complaint.branch,
                          title=title[:120], message=message[:300])
        for account in rules.staff_to_notify(complaint.branch, complaint.urgent)
    )


# POST /api/members/me/complaints - Body: { branch, category, subject, description }.
@api_view(["POST"])
def submit_complaint(request):
    member, denied = _member(request)
    if denied:
        return denied
    serializer = ComplaintSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    if data["branch"] not in rules.complaint_branches(member):
        return Response({"error": {"branch": ["Pick your own branch or one you've visited recently."]}}, status=400)
    with transaction.atomic():
        Member.objects.select_for_update().get(pk=member.pk)
        unresolved = member.complaints.exclude(status=Complaint.Status.RESOLVED).count()
        if unresolved >= rules.MAX_UNRESOLVED:
            return Response({
                "error": f"You have {unresolved} complaints still open - add to one of those, or wait for an answer.",
            }, status=409)
        complaint = Complaint.objects.create(
            member=member, urgent=data["category"] == Complaint.Category.SAFETY, **data,
        )
    flag = "Urgent: " if complaint.urgent else ""
    _notify_staff(complaint, f"{flag}New complaint at {complaint.branch}: {complaint.subject}",
                  f"{member.name} - {complaint.get_category_display()}. Please answer within {rules.RESPONSE_HOURS} hours.")
    return Response(_member_payload(member), status=201)


# POST /api/members/me/complaints/<id>/messages - Body: { body }. Replying to
# a complaint resolved in the last REOPEN_DAYS reopens it.
@api_view(["POST"])
def member_reply(request, complaint_id):
    member, denied = _member(request)
    if denied:
        return denied
    complaint = member.complaints.filter(id=complaint_id).first()
    if complaint is None:
        return Response({"error": "Complaint not found."}, status=404)
    serializer = MessageSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    reopened = False
    if complaint.status == Complaint.Status.RESOLVED:
        if complaint.resolved_at + timedelta(days=rules.REOPEN_DAYS) < timezone.now():
            return Response({"error": "This complaint was closed a while ago - please report a new one."}, status=409)
        complaint.status, complaint.resolved_at, complaint.resolved_by = Complaint.Status.OPEN, None, None
        reopened = True
    ComplaintMessage.objects.create(complaint=complaint, author_member=member, body=serializer.validated_data["body"])
    complaint.save()
    _notify_staff(complaint, f"{'Reopened' if reopened else 'Reply'}: {complaint.subject}",
                  f"{member.name} wrote on their complaint at {complaint.branch}.")
    return Response(_member_payload(member))


# --- the branch manager's side ------------------------------------------------

def _period(request):
    start, end, error = parse_period(request.query_params.get("period"))
    if error:
        return None, Response({"error": {"period": [error]}}, status=400)
    return (start, end), None


def _month_before(start):
    previous_end = start - timedelta(days=1)
    return previous_end.replace(day=1), previous_end


# GET /api/branch-feedback/summary?branch=&period=YYYY-MM - the branch's
# scores, trend, comments, complaint counts and coach ratings for a month.
@api_view(["GET"])
def summary(request):
    account, denied = authorize(request, MANAGE)
    if denied:
        return denied
    branch, branches, error = resolve_branch(account, request.query_params.get("branch"), subject=SUBJECT)
    if error:
        return error
    period, error = _period(request)
    if error:
        return error
    start, end = period
    previous_start, previous_end = _month_before(start)
    trend, month = [], start
    for _ in range(TREND_MONTHS):
        trend.append((period_key(month), f"{month:%b %Y}", month, (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)))
        month = _month_before(month)[0]
    return Response({
        "branch": branch,
        "branches": branches,
        "period": {"key": period_key(start), "label": f"{start:%B %Y}", "start": start, "end": end},
        "periods": available_periods(),
        "areaLabels": [{"key": k, "label": label} for k, label in AREAS],
        "responseHours": rules.RESPONSE_HOURS,
        **rules.summary(branch, start, end, previous_start, previous_end, trend[::-1]),
    })


def _complaint_for(request, complaint_id):
    account, denied = authorize(request, MANAGE)
    if denied:
        return None, None, denied
    complaint = Complaint.objects.select_related("member", "resolved_by").filter(id=complaint_id).first()
    if complaint is None:
        return None, None, Response({"error": "Complaint not found."}, status=404)
    _, _, error = resolve_branch(account, complaint.branch, subject="complaints")
    if error:
        return None, None, error
    return account, complaint, None


STATUS_FILTERS = {"open": [Complaint.Status.OPEN, Complaint.Status.IN_PROGRESS], "resolved": [Complaint.Status.RESOLVED]}


# GET /api/branch-feedback/complaints?branch=&status=open|resolved|all&category=
# Open ones: urgent first, then oldest first (the next to answer at the top).
@api_view(["GET"])
def complaint_list(request):
    account, denied = authorize(request, MANAGE)
    if denied:
        return denied
    branch, _, error = resolve_branch(account, request.query_params.get("branch"), subject="complaints")
    if error:
        return error
    status = request.query_params.get("status", "open")
    if status not in (*STATUS_FILTERS, "all"):
        return Response({"error": {"status": ["Use open, resolved or all."]}}, status=400)
    complaints = Complaint.objects.filter(branch=branch).select_related("member", "resolved_by")
    if status != "all":
        complaints = complaints.filter(status__in=STATUS_FILTERS[status])
    category = request.query_params.get("category")
    if category:
        if category not in Complaint.Category.values:
            return Response({"error": {"category": ["Unknown category."]}}, status=400)
        complaints = complaints.filter(category=category)
    complaints = complaints.prefetch_related("messages__author_staff", "messages__author_member")
    if status == "open":
        complaints = complaints.order_by("-urgent", "created_at")
    else:
        complaints = complaints.order_by("-created_at")
    results = [rules.complaint_payload(c, for_staff=True) for c in complaints[:200]]
    return Response({"branch": branch, "categories": _choices(Complaint.Category), "results": results})


def _staff_detail(complaint):
    complaint = Complaint.objects.select_related("member", "resolved_by").prefetch_related(
        "messages__author_staff", "messages__author_member").get(pk=complaint.pk)
    return rules.complaint_payload(complaint, for_staff=True)


def _tell_member(complaint, title, message):
    if complaint.member is not None:
        notify_member(complaint.member, MemberNotification.Kind.COMPLAINT_UPDATE, title, message)


def _reply(account, complaint, body, internal):
    ComplaintMessage.objects.create(complaint=complaint, author_staff=account, body=body, internal=internal)
    if internal:
        complaint.save(update_fields=["updated_at"])
        return
    if complaint.first_response_at is None:
        complaint.first_response_at = timezone.now()
    if complaint.status == Complaint.Status.OPEN:
        complaint.status = Complaint.Status.IN_PROGRESS
    complaint.save()
    _tell_member(complaint, f"Reply to your complaint: {complaint.subject}", f"{account.full_name}: {body}")


# GET  /api/branch-feedback/complaints/<id> - the complaint and its whole thread (internal notes too).
# PATCH /api/branch-feedback/complaints/<id> - Body: { status, message? }.
@api_view(["GET", "PATCH"])
def complaint_detail(request, complaint_id):
    account, complaint, denied = _complaint_for(request, complaint_id)
    if denied:
        return denied
    if request.method == "GET":
        return Response(_staff_detail(complaint))

    serializer = StatusSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    status, message = serializer.validated_data["status"], serializer.validated_data.get("message", "")
    if status == complaint.status and not message:
        return Response({"error": f"This complaint is already {status.lower()}."}, status=400)
    has_answer = complaint.messages.filter(author_staff__isnull=False, internal=False).exists()
    if status == Complaint.Status.RESOLVED and not (has_answer or message):
        return Response({
            "error": {"message": ["Tell the member what was done before resolving it."]},
        }, status=400)
    with transaction.atomic():
        previous = complaint.status
        if message:
            _reply(account, complaint, message, internal=False)
            complaint.refresh_from_db()
        if status != complaint.status:
            complaint.status = status
            if status == Complaint.Status.RESOLVED:
                complaint.resolved_at, complaint.resolved_by = timezone.now(), account
                if complaint.first_response_at is None:
                    complaint.first_response_at = complaint.resolved_at
            else:
                complaint.resolved_at, complaint.resolved_by = None, None
            complaint.save()
            if status == Complaint.Status.RESOLVED:
                _tell_member(complaint, f"Resolved: {complaint.subject}",
                             f"{complaint.branch} marked your complaint as resolved. Not sorted? Reply within "
                             f"{rules.REOPEN_DAYS} days to reopen it.")
        if previous != complaint.status:
            record(
                request, AuditLog.Action.COMPLAINT_STATUS_CHANGED, actor=account, target=complaint.member,
                branch=complaint.branch, summary=f"Complaint \"{complaint.subject[:80]}\": {previous} -> {complaint.status}",
                details={"complaintId": complaint.id, "from": previous, "to": complaint.status},
            )
    return Response(_staff_detail(complaint))


# POST /api/branch-feedback/complaints/<id>/messages - Body: { body, internal? }.
# A reply (not an internal note) is sent to the member and starts the case.
@api_view(["POST"])
def staff_reply(request, complaint_id):
    account, complaint, denied = _complaint_for(request, complaint_id)
    if denied:
        return denied
    serializer = MessageSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=400)
    data = serializer.validated_data
    if complaint.status == Complaint.Status.RESOLVED and not data["internal"]:
        return Response({"error": "This complaint is resolved - reopen it to reply."}, status=409)
    if complaint.member is None and not data["internal"]:
        return Response({"error": "The member who sent this has deleted their account - only internal notes are possible."}, status=409)
    _reply(account, complaint, data["body"], data["internal"])
    return Response(_staff_detail(complaint), status=201)
