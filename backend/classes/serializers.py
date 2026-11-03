from django.utils import timezone
from rest_framework import serializers

from members.models import Member

from .models import ClassBooking, ClassType, GymClass, PTAvailability, PTSession, TimeOff
from .rules import MAX_CAPACITY, MAX_DURATION, MAX_REPEAT_WEEKS, MIN_DURATION, PT_SESSION_LENGTHS

DATETIME = "%Y-%m-%d %H:%M"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# One class on the calendar. Dates and times are the branch's local time
# (Beirut), split the way the calendar shows them. `state` and `editable`
# come from the server clock, so a stale browser can't offer an edit.
class GymClassSerializer(serializers.ModelSerializer):
    classTypeId = serializers.IntegerField(source="class_type_id")
    # The type's safety limit - the most spots this class could be given.
    maxCapacity = serializers.IntegerField(source="class_type.max_capacity")
    coachId = serializers.IntegerField(source="coach_id")
    coachName = serializers.CharField(source="coach.full_name")
    coachActive = serializers.BooleanField(source="coach.is_active")
    date = serializers.SerializerMethodField()
    startTime = serializers.SerializerMethodField()
    endTime = serializers.SerializerMethodField()
    durationMinutes = serializers.SerializerMethodField()
    booked = serializers.SerializerMethodField()
    spotsLeft = serializers.SerializerMethodField()
    cancelReason = serializers.CharField(source="cancel_reason")
    seriesId = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    editable = serializers.BooleanField(source="is_editable")

    class Meta:
        model = GymClass
        fields = [
            "id", "branch", "classTypeId", "name", "description", "coachId", "coachName", "coachActive", "room",
            "date", "startTime", "endTime", "durationMinutes", "capacity", "maxCapacity", "booked", "spotsLeft",
            "status", "cancelReason", "seriesId", "state", "editable",
        ]

    def get_date(self, obj):
        return timezone.localtime(obj.starts_at).date().isoformat()

    def get_startTime(self, obj):
        return f"{timezone.localtime(obj.starts_at):%H:%M}"

    def get_endTime(self, obj):
        return f"{timezone.localtime(obj.ends_at):%H:%M}"

    def get_durationMinutes(self, obj):
        return int((obj.ends_at - obj.starts_at).total_seconds() // 60)

    # Views annotate booked_count; counted directly otherwise.
    def get_booked(self, obj):
        count = getattr(obj, "booked_count", None)
        return count if count is not None else obj.bookings.filter(status=ClassBooking.Status.BOOKED).count()

    # What can actually still be booked: the class's spots, and never past its
    # type's safety limit (the same limit booking enforces).
    def get_spotsLeft(self, obj):
        return max(0, min(obj.capacity, obj.class_type.max_capacity) - self.get_booked(obj))

    def get_seriesId(self, obj):
        return str(obj.series) if obj.series else None

    def get_state(self, obj):
        if obj.status == GymClass.Status.CANCELLED:
            return "cancelled"
        now = timezone.now()
        if obj.ends_at <= now:
            return "finished"
        if obj.starts_at <= now:
            return "in_progress"
        return "upcoming"


class RosterEntrySerializer(serializers.ModelSerializer):
    bookingId = serializers.IntegerField(source="id")
    memberId = serializers.IntegerField(source="member_id")
    memberName = serializers.CharField(source="member.name")
    bookedAt = serializers.DateTimeField(source="booked_at", format=DATETIME)
    # Who booked it at the front desk; null when the member booked it themselves.
    bookedBy = serializers.CharField(source="booked_by.full_name", default=None)
    cancelReason = serializers.CharField(source="cancel_reason")

    class Meta:
        model = ClassBooking
        fields = ["bookingId", "memberId", "memberName", "status", "bookedAt", "bookedBy", "cancelReason", "attendance"]


# POST /api/classes/<id>/bookings
class DeskBookingSerializer(serializers.Serializer):
    memberId = serializers.IntegerField(min_value=1)


class MyBookingSerializer(serializers.ModelSerializer):
    bookedAt = serializers.DateTimeField(source="booked_at", format=DATETIME)
    cancelReason = serializers.CharField(source="cancel_reason")

    class Meta:
        model = ClassBooking
        fields = ["id", "status", "bookedAt", "cancelReason", "attendance"]


def _five_minute_steps(value):
    if value % 5:
        raise serializers.ValidationError("Use 5-minute steps.")
    return value


# The class's name comes from its type. Spots and length default to the
# type's maximum and default length when left out.
class _ClassFields(serializers.Serializer):
    classTypeId = serializers.IntegerField(min_value=1)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    coachId = serializers.IntegerField(min_value=1)
    room = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    date = serializers.DateField()
    startTime = serializers.TimeField(input_formats=["%H:%M", "%H:%M:%S"])
    durationMinutes = serializers.IntegerField(min_value=MIN_DURATION, max_value=MAX_DURATION, required=False)
    capacity = serializers.IntegerField(min_value=1, max_value=MAX_CAPACITY, required=False)

    def validate_room(self, value):
        return " ".join(value.split())

    def validate_durationMinutes(self, value):
        return _five_minute_steps(value)


# POST /api/classes
class GymClassCreateSerializer(_ClassFields):
    branch = serializers.ChoiceField(choices=Member.Branch.choices, required=False)
    # 1 = just this date; N = the same slot every week for N weeks.
    repeatWeeks = serializers.IntegerField(min_value=1, max_value=MAX_REPEAT_WEEKS, required=False, default=1)


# PATCH /api/classes/<id>. "following" applies the change to this class and
# the later ones in its weekly series (each keeps its own date).
class GymClassUpdateSerializer(_ClassFields):
    scope = serializers.ChoiceField(choices=["one", "following"], required=False, default="one")


# POST /api/classes/<id>/cancel
class CancelClassSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    scope = serializers.ChoiceField(choices=["one", "following"], required=False, default="one")


# A class type with what's riding on its maximum: how many upcoming classes
# use it, and the most bookings any of them already has (the floor the
# maximum can't drop below). Views pass those in context["stats"].
class ClassTypeSerializer(serializers.ModelSerializer):
    maxCapacity = serializers.IntegerField(source="max_capacity")
    defaultDurationMinutes = serializers.IntegerField(source="default_duration_minutes")
    isActive = serializers.BooleanField(source="is_active")
    upcomingClasses = serializers.SerializerMethodField()
    mostBookedUpcoming = serializers.SerializerMethodField()

    class Meta:
        model = ClassType
        fields = [
            "id", "branch", "name", "maxCapacity", "defaultDurationMinutes", "description", "isActive",
            "upcomingClasses", "mostBookedUpcoming",
        ]

    def _stats(self, obj):
        return self.context.get("stats", {}).get(obj.id, {"upcomingClasses": 0, "mostBooked": 0})

    def get_upcomingClasses(self, obj):
        return self._stats(obj)["upcomingClasses"]

    def get_mostBookedUpcoming(self, obj):
        return self._stats(obj)["mostBooked"]


# POST /api/classes/types and PATCH /api/classes/types/<id>. Names are unique
# per branch, ignoring case; context["branch"] is the type's branch.
class ClassTypeWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=60)
    maxCapacity = serializers.IntegerField(min_value=1, max_value=MAX_CAPACITY)
    defaultDurationMinutes = serializers.IntegerField(
        min_value=MIN_DURATION, max_value=MAX_DURATION, required=False, default=60,
    )
    description = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    isActive = serializers.BooleanField(required=False)

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Give the class type a name.")
        branch = self.context["branch"]
        taken = ClassType.objects.filter(branch=branch, name__iexact=value)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError(f"{branch} already has a {value} class type.")
        return value

    def validate_defaultDurationMinutes(self, value):
        return _five_minute_steps(value)


# --- Private training ---

# One weekly block of a coach's PT hours.
class PTHoursSerializer(serializers.ModelSerializer):
    coachId = serializers.IntegerField(source="coach_id")
    day = serializers.SerializerMethodField()
    startTime = serializers.TimeField(source="start_time", format="%H:%M")
    endTime = serializers.TimeField(source="end_time", format="%H:%M")
    sessionMinutes = serializers.IntegerField(source="session_minutes")

    class Meta:
        model = PTAvailability
        fields = ["id", "coachId", "branch", "weekday", "day", "startTime", "endTime", "sessionMinutes"]

    def get_day(self, obj):
        return WEEKDAYS[obj.weekday]


# Shared by the branch manager's "add PT hours for a coach" and the coach's
# own "set my PT hours" - everything but who the hours are for.
class _PTHoursFields(serializers.Serializer):
    branch = serializers.ChoiceField(choices=Member.Branch.choices, required=False)
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    startTime = serializers.TimeField(input_formats=["%H:%M"])
    endTime = serializers.TimeField(input_formats=["%H:%M"])
    sessionMinutes = serializers.ChoiceField(choices=PT_SESSION_LENGTHS)

    def validate(self, attrs):
        start, end = attrs["startTime"], attrs["endTime"]
        if start.minute % 5 or end.minute % 5:
            raise serializers.ValidationError({"startTime": ["Use 5-minute steps."]})
        minutes = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
        if minutes <= 0:
            raise serializers.ValidationError({"endTime": ["The hours have to end after they start."]})
        if minutes < attrs["sessionMinutes"]:
            raise serializers.ValidationError(
                {"endTime": [f"That's shorter than one {attrs['sessionMinutes']}-minute session."]},
            )
        return attrs


# POST /api/classes/pt-hours
class PTHoursCreateSerializer(_PTHoursFields):
    coachId = serializers.IntegerField(min_value=1)


# POST /api/classes/me/pt-hours - same fields, minus coachId: it's always
# the signed-in coach.
class MyPTHoursCreateSerializer(_PTHoursFields):
    pass


class PTSessionSerializer(serializers.ModelSerializer):
    coachId = serializers.IntegerField(source="coach_id")
    coachName = serializers.CharField(source="coach.full_name")
    memberId = serializers.IntegerField(source="member_id")
    memberName = serializers.CharField(source="member.name")
    date = serializers.SerializerMethodField()
    startTime = serializers.SerializerMethodField()
    endTime = serializers.SerializerMethodField()
    cancelReason = serializers.CharField(source="cancel_reason")
    bookedAt = serializers.DateTimeField(source="booked_at", format=DATETIME)
    state = serializers.SerializerMethodField()

    class Meta:
        model = PTSession
        fields = [
            "id", "coachId", "coachName", "memberId", "memberName", "branch", "date", "startTime", "endTime",
            "status", "note", "cancelReason", "attendance", "bookedAt", "state",
        ]

    def get_date(self, obj):
        return timezone.localtime(obj.starts_at).date().isoformat()

    def get_startTime(self, obj):
        return f"{timezone.localtime(obj.starts_at):%H:%M}"

    def get_endTime(self, obj):
        return f"{timezone.localtime(obj.ends_at):%H:%M}"

    def get_state(self, obj):
        if obj.status == PTSession.Status.CANCELLED:
            return "cancelled"
        now = timezone.now()
        if obj.ends_at <= now:
            return "finished"
        return "in_progress" if obj.starts_at <= now else "upcoming"


# POST /api/members/me/pt-sessions - startsAt is the slot's local (Beirut)
# start, "YYYY-MM-DDTHH:MM", as /me/pt-slots lists it.
class PTBookSerializer(serializers.Serializer):
    coachId = serializers.IntegerField(min_value=1)
    startsAt = serializers.DateTimeField(input_formats=["%Y-%m-%dT%H:%M"])
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


# POST /api/classes/pt-sessions/<id>/cancel
class StaffCancelPTSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


# --- A coach's own time off ---

class TimeOffSerializer(serializers.ModelSerializer):
    coachId = serializers.IntegerField(source="coach_id")
    startsAt = serializers.DateTimeField(source="starts_at", format=DATETIME)
    endsAt = serializers.DateTimeField(source="ends_at", format=DATETIME)
    state = serializers.SerializerMethodField()

    class Meta:
        model = TimeOff
        fields = ["id", "coachId", "startsAt", "endsAt", "reason", "state"]

    def get_state(self, obj):
        now = timezone.now()
        if obj.ends_at <= now:
            return "finished"
        return "in_progress" if obj.starts_at <= now else "upcoming"


# POST /api/classes/me/time-off
class TimeOffCreateSerializer(serializers.Serializer):
    startsAt = serializers.DateTimeField(input_formats=["%Y-%m-%dT%H:%M"])
    endsAt = serializers.DateTimeField(input_formats=["%Y-%m-%dT%H:%M"])
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["endsAt"] <= attrs["startsAt"]:
            raise serializers.ValidationError({"endsAt": ["Has to be after the start."]})
        return attrs
