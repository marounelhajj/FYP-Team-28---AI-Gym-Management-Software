from contextlib import contextmanager
from datetime import datetime, time, timedelta

from django.utils import timezone

from administration.models import Role, StaffAccount
from audit.models import AuditLog
from billing.models import Payment
from checkins.models import CheckIn
from members.models import Member
from training.models import TrainingEvent

# Builders for the churn tests: members with a crafted history.

PASSWORD = "ChangeMe123!"


def staff(username, permissions, branch=None, job_title=StaffAccount.JobTitle.BRANCH_MANAGER, role_name=None):
    role, _ = Role.objects.get_or_create(name=role_name or f"{username} role", defaults={"permissions": permissions})
    account = StaffAccount(
        full_name=username.title(), email=f"{username}@gym.com", username=username,
        job_title=job_title, role=role, branch=branch,
    )
    account.set_password(PASSWORD)
    account.save()
    return account


def at(day, hour=18):
    return timezone.make_aware(datetime.combine(day, time(hour, 0)))


def member(name, branch="Hamra", joined_days_ago=400, expires_in=60, status=Member.Status.ACTIVE, today=None):
    today = today or timezone.localdate()
    return Member.objects.create(
        name=name, email=f"{name.split()[0].lower()}@example.com", phone="1", branch=branch, status=status,
        join_date=today - timedelta(days=joined_days_ago),
        subscription_expires_at=today + timedelta(days=expires_in) if expires_in is not None else None,
    )


# checked_in_at / paid_at are auto_now_add; this lets a test (or the demo
# seed) write them in the past in one bulk insert.
@contextmanager
def backdating(model, field_name):
    field = model._meta.get_field(field_name)
    field.auto_now_add = False
    try:
        yield
    finally:
        field.auto_now_add = True


# Check-ins on the given days ago (allowed).
def visits(m, days_ago, today=None):
    today = today or timezone.localdate()
    with backdating(CheckIn, "checked_in_at"):
        CheckIn.objects.bulk_create([
            CheckIn(member=m, result=CheckIn.Result.ALLOWED, branch=m.branch,
                    checked_in_at=at(today - timedelta(days=back)), checked_out_at=at(today - timedelta(days=back), 19))
            for back in days_ago
        ])


# A steady regular: `per_week` visits a week for the last `weeks` weeks.
def regular(m, per_week=3, weeks=12, skip_recent_weeks=0, recent_per_week=None, today=None):
    days = []
    for week in range(weeks):
        n = per_week
        if week < 4 and recent_per_week is not None:
            n = recent_per_week
        if week < skip_recent_weeks:
            n = 0
        days.extend(week * 7 + 1 + 2 * i for i in range(n))
    visits(m, days, today=today)


def payment(m, paid_days_ago, expires_days_from_today, today=None):
    today = today or timezone.localdate()
    p = Payment.objects.create(
        member=m, amount="40.00", method=Payment.Method.CASH, duration=Payment.Duration.ONE_MONTH,
        expires_at=today + timedelta(days=expires_days_from_today),
    )
    Payment.objects.filter(pk=p.pk).update(paid_at=at(today - timedelta(days=paid_days_ago), 10))
    return p


def cancel(m, days_ago, today=None):
    today = today or timezone.localdate()
    m.status = Member.Status.CANCELLED
    m.save(update_fields=["status"])
    TrainingEvent.objects.create(
        event_type=TrainingEvent.EventType.CANCELLATION, member=m, branch=m.branch,
        occurred_at=at(today - timedelta(days=days_ago), 12),
    )


def froze(m, days_ago, today=None):
    today = today or timezone.localdate()
    entry = AuditLog(
        action=AuditLog.Action.MEMBER_FROZEN, actor_type=AuditLog.ActorType.MEMBER, actor_member=m,
        target_type="member", target_id=str(m.pk), target_label=m.name, branch=m.branch, summary="froze",
    )
    entry.created_at = at(today - timedelta(days=days_ago), 9)
    entry.save()
