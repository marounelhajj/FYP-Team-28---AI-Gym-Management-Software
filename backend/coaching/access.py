from datetime import timedelta

from django.utils import timezone

from classes.models import PTSession
from progress.views import assigned_members

# Who may write and read coaching logs.
#
#   * A session is logged by its own coach, from the moment it starts until
#     EDIT_DAYS after it ends. After that the log is locked, so a client's
#     history can be trusted not to be rewritten later.
#   * A client's progress (every coach's logs, their goals) can be read, and
#     goals set, by any coach the client has booked private training with -
#     the same "assigned coach" rule as their self-logged workouts (SCRUM-60).
#   * The member reads their own, without the coaches' private assessments.

EDIT_DAYS = 7


# Why this coach can't log or change the log of this session now, as
# (http status, message), or None.
def edit_problem(coach, session, now=None):
    now = now or timezone.now()
    if session.coach_id != coach.id:
        return 403, "Only the coach of this session can log it."
    if session.status == PTSession.Status.CANCELLED:
        return 409, "This session was cancelled."
    if session.starts_at > now:
        return 409, "You can log a session once it has started."
    if session.ends_at + timedelta(days=EDIT_DAYS) < now:
        return 409, f"Logs lock {EDIT_DAYS} days after the session, so the client's history stays as it was written."
    return None


def coaches_member(coach, member_id):
    return assigned_members(coach).filter(id=member_id).first()
