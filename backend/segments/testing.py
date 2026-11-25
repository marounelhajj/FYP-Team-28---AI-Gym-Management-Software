from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from administration.models import StaffAccount
from churn.models import ChurnRun, ChurnScore, Method
from churn.testing import PASSWORD, at, member, staff, visits  # noqa: F401  (re-exported for the tests)
from classes.models import ClassBooking, ClassType, GymClass, PTSession
from notifications.models import NotificationSettings
from retail.models import Product, Sale, SaleItem

# Builders for the segment tests.

SEGMENT_ROLE = ["manage_member_segments", "view_member_segments", "export_segment_members"]


def marketing(username="nadine"):
    return staff(username, SEGMENT_ROLE, job_title=StaffAccount.JobTitle.MARKETING_STAFF, role_name="Marketing Staff")


def branch_manager(username="hamrabm", branch="Hamra"):
    return staff(username, ["view_member_segments"], branch=branch, role_name=f"{username} BM")


def coach(username="coachy"):
    existing = StaffAccount.objects.filter(username=username).first()
    return existing or staff(username, [], job_title=StaffAccount.JobTitle.COACH, role_name="Coach role")


def checkins(m, days_ago, hour=18, today=None):
    """Allowed check-ins on the given days ago, at the given hour."""
    from checkins.models import CheckIn
    from churn.testing import backdating

    today = today or timezone.localdate()
    with backdating(CheckIn, "checked_in_at"):
        CheckIn.objects.bulk_create([
            CheckIn(member=m, result=CheckIn.Result.ALLOWED, branch=m.branch,
                    checked_in_at=at(today - timedelta(days=d), hour),
                    checked_out_at=at(today - timedelta(days=d), hour + 1))
            for d in days_ago
        ])


def class_type(name, branch="Hamra"):
    obj, _ = ClassType.objects.get_or_create(branch=branch, name=name, defaults={"max_capacity": 20})
    return obj


def attended_class(m, type_name, days_ago, hour=18, today=None):
    today = today or timezone.localdate()
    ct = class_type(type_name, m.branch)
    start = at(today - timedelta(days=days_ago), hour)
    gym_class = GymClass.objects.create(
        branch=m.branch, class_type=ct, name=type_name, coach=coach(), starts_at=start,
        ends_at=start + timedelta(hours=1), capacity=20,
    )
    return ClassBooking.objects.create(gym_class=gym_class, member=m, attendance=ClassBooking.Attendance.ATTENDED)


def pt_session(m, days_ago, hour=7, today=None, cancelled=False, coach_username="coachy"):
    today = today or timezone.localdate()
    start = at(today - timedelta(days=days_ago), hour)
    return PTSession.objects.create(
        coach=coach(coach_username), member=m, branch=m.branch, starts_at=start, ends_at=start + timedelta(hours=1),
        status=PTSession.Status.CANCELLED if cancelled else PTSession.Status.BOOKED,
    )


def purchase(m, category, days_ago, quantity=1, price="5.00", today=None):
    today = today or timezone.localdate()
    product, _ = Product.objects.get_or_create(
        name=f"{category} item", defaults={"category": category, "price": Decimal(price)},
    )
    sale = Sale.objects.create(
        branch=m.branch, member=m, payment_method=Sale.PaymentMethod.CASH,
        total=Decimal(price) * quantity, sold_at=at(today - timedelta(days=days_ago), 12),
    )
    SaleItem.objects.create(
        sale=sale, product=product, product_name=product.name, unit_price=Decimal(price), quantity=quantity,
        line_total=Decimal(price) * quantity,
    )
    return sale


def risk(m, level, today=None):
    today = today or timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    run, _ = ChurnRun.objects.get_or_create(
        branch=m.branch, week_start=monday,
        defaults={"as_of": today, "method": Method.RULES, "trigger": ChurnRun.Trigger.MANUAL},
    )
    rank = ChurnScore.objects.filter(run=run).count() + 1
    return ChurnScore.objects.create(
        run=run, branch=m.branch, week_start=monday, member=m, rank=rank,
        score={"High": 80, "Medium": 50, "Low": 10}[level], level=level, method=Method.RULES,
    )


def opt_out(m):
    NotificationSettings.objects.update_or_create(member=m, defaults={"offers": False})
