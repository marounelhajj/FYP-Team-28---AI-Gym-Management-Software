import logging

from django.db import transaction

from .models import TrainingEvent

logger = logging.getLogger(__name__)

# The one way training events get written. Call it right after the action
# succeeds:
#
#   log_training_event(TrainingEvent.EventType.CHECK_IN, member=member, branch=branch,
#                      payload={"checkInId": check_in.id})
#
# Logging must never break the action it describes: if the write fails, the
# error is logged and None is returned, and the check-in / cancellation
# carries on as normal. The savepoint keeps a failed insert from poisoning a
# surrounding transaction.
#
# Wired today: check_in (checkins/views.py) and cancellation
# (members/views.py, front desk and self-service).
#
# TODO(no_show): there are no class or PT bookings yet. When they land, call
#   log_training_event(TrainingEvent.EventType.NO_SHOW, member=..., branch=...,
#                      trainer=<coach or None>, session_id=str(<booking id>))
# from wherever a booking is marked as missed (or from the job that closes
# sessions nobody checked into).
# TODO(trainer_accept / trainer_reject): there is no coach-request flow yet.
# When a coach accepts or rejects a PT request or program, call
#   log_training_event(TrainingEvent.EventType.TRAINER_ACCEPT (or TRAINER_REJECT),
#                      member=..., branch=..., trainer=<coach>, session_id=str(<request id>),
#                      payload={"reason": <rejection reason, if any>})
# from that view.


def log_training_event(event_type, *, member, branch=None, trainer=None, session_id="", payload=None, occurred_at=None):
    try:
        fields = {
            "event_type": event_type,
            "member": member,
            "branch": branch or member.branch,
            "trainer": trainer,
            "session_id": str(session_id or ""),
            "payload": payload or {},
        }
        if occurred_at is not None:
            fields["occurred_at"] = occurred_at
        with transaction.atomic():
            return TrainingEvent.objects.create(**fields)
    except Exception:
        logger.exception("Couldn't log %s training event for member %s", event_type, getattr(member, "pk", member))
        return None


# Removes every training event about one member. For the member data
# export/deletion request flow (SCRUM-62), which should call this when it
# erases a member. Returns how many events were deleted.
def delete_training_events_for_member(member_id):
    deleted, _ = TrainingEvent.objects.filter(member_id=member_id).delete()
    return deleted
