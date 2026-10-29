from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone

from administration.models import StaffAccount
from members.models import Member

# User story: "As a branch manager, I want to create and edit class schedules
# and assign coaches to time slots, so that I can build the weekly class
# calendar for my branch."
#
# One row per class on the calendar (a 18:00 Spinning on Thursday 29 October
# is one GymClass; the same class next Thursday is another). Classes made
# together with "repeat weekly" share a series id, so they can later be
# edited or cancelled together. The rules - coaches and studios can't be in
# two places at once, members can't book two classes at the same time,
# anything that has started is view-only - live in rules.py and views.py.


# User story: "As a branch manager, I want to set maximum capacity per class
# type, so that I can prevent overbooking and keep sessions safe."
#
# A kind of class a branch runs ("Spinning at Hamra") and the most people one
# class of it can safely hold there - the bikes in the cycle studio, the mats,
# one coach's group size. Every class of the type gets at most that many
# spots. Types belong to one branch, since studios and equipment differ.
class ClassType(models.Model):
    branch = models.CharField(max_length=30, choices=Member.Branch.choices, db_index=True)
    name = models.CharField(max_length=60)
    max_capacity = models.PositiveSmallIntegerField()
    # Pre-fills the length when a class of this type is scheduled.
    default_duration_minutes = models.PositiveSmallIntegerField(default=60)
    description = models.CharField(max_length=300, blank=True)
    # Archived types can't be scheduled any more; their classes stay.
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["branch", "name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), "branch", name="one_class_type_name_per_branch"),
        ]

    def __str__(self):
        return f"{self.name} at {self.branch} (max {self.max_capacity})"


class GymClass(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "Scheduled", "Scheduled"
        CANCELLED = "Cancelled", "Cancelled"

    branch = models.CharField(max_length=30, choices=Member.Branch.choices, db_index=True)
    class_type = models.ForeignKey(ClassType, on_delete=models.PROTECT, related_name="classes")
    # The type's name when the class was scheduled. Renaming a type renames
    # its upcoming classes; past ones keep the name they ran under.
    name = models.CharField(max_length=60)
    description = models.CharField(max_length=300, blank=True)
    coach = models.ForeignKey(StaffAccount, on_delete=models.PROTECT, related_name="coached_classes")
    # The studio or room inside the branch ("Studio A"). Optional; when set,
    # no two classes can use it at the same time.
    room = models.CharField(max_length=40, blank=True)
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    # Spots in this class - never more than its type's max_capacity.
    capacity = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    series = models.UUIDField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    cancel_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["starts_at", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="class_ends_after_it_starts"),
        ]

    def __str__(self):
        return f"{self.name} at {self.branch}, {timezone.localtime(self.starts_at):%Y-%m-%d %H:%M}"

    @property
    def has_started(self):
        return self.starts_at <= timezone.now()

    # Only a class that hasn't started yet can be changed or cancelled - once
    # it starts (and so for every day that has passed) it's view-only.
    @property
    def is_editable(self):
        return self.status == self.Status.SCHEDULED and not self.has_started


class ClassBooking(models.Model):
    class Status(models.TextChoices):
        BOOKED = "Booked", "Booked"
        CANCELLED = "Cancelled", "Cancelled"

    class Attendance(models.TextChoices):
        ATTENDED = "Attended", "Attended"
        NO_SHOW = "No-show", "No-show"

    gym_class = models.ForeignKey(GymClass, on_delete=models.CASCADE, related_name="bookings")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="class_bookings")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.BOOKED)
    booked_at = models.DateTimeField(default=timezone.now)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    # Why it ended: the member cancelled, the gym cancelled the class, or the
    # membership was frozen or cancelled.
    cancel_reason = models.CharField(max_length=60, blank=True)
    # Filled in once the class is over, from the member's check-ins (see
    # rules.settle_attendance). Blank until then.
    attendance = models.CharField(max_length=10, choices=Attendance.choices, blank=True)

    class Meta:
        ordering = ["booked_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["gym_class", "member"], condition=Q(status="Booked"),
                name="one_live_booking_per_member_per_class",
            ),
        ]

    def __str__(self):
        return f"{self.member} -> {self.gym_class} ({self.status})"


# User story: "As a member, I want to browse and book available classes or PT
# sessions directly through the app, so that I can reserve my spot without
# contacting the front desk."
#
# Private training (PT): one member, one coach. A branch manager publishes
# each coach's weekly PT hours at a branch (PTAvailability); those hours are
# cut into sessions of session_minutes, and a member books a free one
# (PTSession). A session is free while the coach has no other session or
# group class then - see rules.pt_slots.
class PTAvailability(models.Model):
    coach = models.ForeignKey(StaffAccount, on_delete=models.CASCADE, related_name="pt_hours")
    branch = models.CharField(max_length=30, choices=Member.Branch.choices)
    weekday = models.PositiveSmallIntegerField()  # 0 = Monday ... 6 = Sunday
    start_time = models.TimeField()
    end_time = models.TimeField()
    session_minutes = models.PositiveSmallIntegerField(default=60)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["weekday", "start_time"]
        constraints = [
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="pt_hours_end_after_start"),
            models.CheckConstraint(condition=Q(weekday__lte=6), name="pt_hours_weekday_0_to_6"),
        ]

    def __str__(self):
        return f"{self.coach.full_name} PT at {self.branch}, day {self.weekday} {self.start_time}-{self.end_time}"


class PTSession(models.Model):
    class Status(models.TextChoices):
        BOOKED = "Booked", "Booked"
        CANCELLED = "Cancelled", "Cancelled"

    coach = models.ForeignKey(StaffAccount, on_delete=models.PROTECT, related_name="pt_sessions")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="pt_sessions")
    branch = models.CharField(max_length=30, choices=Member.Branch.choices)
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.BOOKED)
    # What the member wants to work on ("knee rehab"), for the coach.
    note = models.CharField(max_length=200, blank=True)
    booked_at = models.DateTimeField(default=timezone.now)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=120, blank=True)
    # Filled in once the session is over, from check-ins (rules.settle_attendance).
    attendance = models.CharField(max_length=10, choices=ClassBooking.Attendance.choices, blank=True)

    class Meta:
        ordering = ["starts_at", "id"]
        constraints = [
            # The last line of defence against two members getting one slot.
            models.UniqueConstraint(
                fields=["coach", "starts_at"], condition=Q(status="Booked"), name="one_live_pt_session_per_coach_slot",
            ),
        ]

    def __str__(self):
        return f"PT {self.coach.full_name} with {self.member} at {timezone.localtime(self.starts_at):%Y-%m-%d %H:%M}"

    @property
    def has_started(self):
        return self.starts_at <= timezone.now()
