from django.db.models import Sum
from django.utils import timezone

from .models import LoyaltyPointEntry

# Point values. Round numbers, easy to explain to a member at the desk -
# tune here if the business wants a different rate; nothing else encodes
# the amount.
SESSION_POINTS = 10
REFERRAL_POINTS = 50


# Called from classes.rules.settle_attendance() the moment a booking is
# settled Attended (never for a No-show). get_or_create (backed by the
# model's unique constraint) means calling this twice for the same
# booking/session - e.g. two requests racing to settle attendance - only
# ever pays out once.
def award_class_attendance(booking):
    return LoyaltyPointEntry.objects.get_or_create(
        class_booking=booking,
        defaults={"member": booking.member, "points": SESSION_POINTS, "reason": LoyaltyPointEntry.Reason.CLASS_ATTENDED},
    )


def award_pt_attendance(session):
    return LoyaltyPointEntry.objects.get_or_create(
        pt_session=session,
        defaults={"member": session.member, "points": SESSION_POINTS, "reason": LoyaltyPointEntry.Reason.PT_ATTENDED},
    )


# Called from members.serializers once a referred member's registration
# (and first payment) has committed - see MemberCreateSerializer/
# MemberSignupSerializer.create(). Points go to `referrer`, the member
# whose code was used, not the new member themselves.
def award_referral(referrer, referred_member):
    return LoyaltyPointEntry.objects.get_or_create(
        referred_member=referred_member,
        defaults={"member": referrer, "points": REFERRAL_POINTS, "reason": LoyaltyPointEntry.Reason.REFERRAL},
    )


def balance(member):
    total = LoyaltyPointEntry.objects.filter(member=member).aggregate(total=Sum("points"))["total"]
    return total or 0


def _describe(entry):
    if entry.reason == LoyaltyPointEntry.Reason.CLASS_ATTENDED and entry.class_booking_id:
        c = entry.class_booking.gym_class
        return f"Attended {c.name} on {timezone.localtime(c.starts_at):%b %d}"
    if entry.reason == LoyaltyPointEntry.Reason.PT_ATTENDED and entry.pt_session_id:
        s = entry.pt_session
        return f"Attended a private training session on {timezone.localtime(s.starts_at):%b %d}"
    if entry.reason == LoyaltyPointEntry.Reason.REFERRAL and entry.referred_member_id:
        return f"Referred {entry.referred_member.name}, who joined"
    return entry.get_reason_display()


# { balance, referralCode, entries: [{points, description, earnedAt}, ...] } -
# everything the member's own loyalty screen shows (see loyalty.views.my_loyalty).
def summary(member, limit=50):
    entries = (
        LoyaltyPointEntry.objects.filter(member=member)
        .select_related("class_booking__gym_class", "pt_session", "referred_member")[:limit]
    )
    return {
        "balance": balance(member),
        "referralCode": member.referral_code,
        "entries": [
            {
                "id": e.id,
                "points": e.points,
                "reason": e.reason,
                "description": _describe(e),
                "earnedAt": timezone.localtime(e.earned_at).strftime("%Y-%m-%d %H:%M"),
            }
            for e in entries
        ],
    }
