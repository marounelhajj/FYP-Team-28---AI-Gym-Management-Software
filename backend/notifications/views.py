from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from administration.permissions import get_staff_account
from members.models import Member

from .models import MemberNotification, StaffNotification

LIMIT = 30


def _data(n):
    return {
        "id": n.id,
        "kind": n.kind,
        "branch": getattr(n, "branch", ""),
        "title": n.title,
        "message": n.message,
        "createdAt": timezone.localtime(n.created_at).strftime("%Y-%m-%d %H:%M"),
        "read": n.read_at is not None,
    }


def _account(request):
    account = get_staff_account(request)
    if account is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    return account, None


# GET /api/notifications - the signed-in staff member's own notifications,
# newest first (at most LIMIT), with how many are unread. Any staff account:
# it only ever returns their own.
@api_view(["GET"])
def my_notifications(request):
    account, denied = _account(request)
    if denied:
        return denied
    mine = StaffNotification.objects.filter(recipient=account)
    return Response({
        "unread": mine.filter(read_at__isnull=True).count(),
        "results": [_data(n) for n in mine[:LIMIT]],
    })


# POST /api/notifications/<id>/read - mark one as read (only your own).
@api_view(["POST"])
def read_one(request, notification_id):
    account, denied = _account(request)
    if denied:
        return denied
    updated = StaffNotification.objects.filter(id=notification_id, recipient=account, read_at__isnull=True).update(
        read_at=timezone.now(),
    )
    if not updated and not StaffNotification.objects.filter(id=notification_id, recipient=account).exists():
        return Response({"error": "Notification not found."}, status=404)
    return Response({"ok": True})


# POST /api/notifications/read-all
@api_view(["POST"])
def read_all(request):
    account, denied = _account(request)
    if denied:
        return denied
    StaffNotification.objects.filter(recipient=account, read_at__isnull=True).update(read_at=timezone.now())
    return Response({"ok": True})


# --- The member's own notifications (member session; routed under /api/members/me/notifications) ---

def _member(request):
    member_id = request.session.get("member_id")
    member = Member.objects.filter(id=member_id).first() if member_id else None
    if member is None:
        return None, Response({"error": "Not authenticated."}, status=401)
    return member, None


# GET /api/members/me/notifications - same shape as the staff list above.
@api_view(["GET"])
def my_member_notifications(request):
    member, denied = _member(request)
    if denied:
        return denied
    mine = MemberNotification.objects.filter(recipient=member)
    return Response({
        "unread": mine.filter(read_at__isnull=True).count(),
        "results": [_data(n) for n in mine[:LIMIT]],
    })


# POST /api/members/me/notifications/<id>/read
@api_view(["POST"])
def member_read_one(request, notification_id):
    member, denied = _member(request)
    if denied:
        return denied
    updated = MemberNotification.objects.filter(id=notification_id, recipient=member, read_at__isnull=True).update(
        read_at=timezone.now(),
    )
    if not updated and not MemberNotification.objects.filter(id=notification_id, recipient=member).exists():
        return Response({"error": "Notification not found."}, status=404)
    return Response({"ok": True})


# POST /api/members/me/notifications/read-all
@api_view(["POST"])
def member_read_all(request):
    member, denied = _member(request)
    if denied:
        return denied
    MemberNotification.objects.filter(recipient=member, read_at__isnull=True).update(read_at=timezone.now())
    return Response({"ok": True})
