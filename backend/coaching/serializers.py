from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from progress.models import EXERCISES, WorkoutEntry

from .models import ClientGoal

MAX_EXERCISES = 30
NOTE_LIMIT = 1000
GOAL_HORIZON_DAYS = 2 * 365


def _range(name, low, high, unit=""):
    def check(value):
        if value is not None and not low <= value <= high:
            raise serializers.ValidationError(f"{name} should be between {low} and {high}{unit}.")
        return value
    return check


# One exercise in a session log - the same rules as the member's own log:
# strength needs sets and reps, cardio a duration or a distance.
class ExerciseSerializer(serializers.Serializer):
    exercise = serializers.CharField(max_length=80)
    kind = serializers.ChoiceField(choices=WorkoutEntry.Kind.choices, required=False)
    sets = serializers.IntegerField(required=False, allow_null=True, validators=[_range("Sets", 1, 20)])
    reps = serializers.IntegerField(required=False, allow_null=True, validators=[_range("Reps", 1, 100)])
    weightKg = serializers.DecimalField(
        max_digits=5, decimal_places=1, required=False, allow_null=True,
        validators=[_range("Weight", Decimal("0"), Decimal("500"), " kg")],
    )
    durationMinutes = serializers.IntegerField(
        required=False, allow_null=True, validators=[_range("Duration", 1, 600, " minutes")],
    )
    distanceKm = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True,
        validators=[_range("Distance", Decimal("0.1"), Decimal("200"), " km")],
    )
    rpe = serializers.IntegerField(required=False, allow_null=True, validators=[_range("Effort (RPE)", 1, 10)])
    note = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate(self, attrs):
        name = " ".join(attrs["exercise"].split())
        if not name:
            raise serializers.ValidationError({"exercise": ["Pick or type an exercise."]})
        kind = EXERCISES.get(name) or attrs.get("kind") or WorkoutEntry.Kind.STRENGTH
        attrs["exercise"], attrs["kind"] = name, kind
        if kind == WorkoutEntry.Kind.STRENGTH:
            errors = {}
            if not attrs.get("sets"):
                errors["sets"] = ["How many sets?"]
            if not attrs.get("reps"):
                errors["reps"] = ["How many reps per set?"]
            if errors:
                raise serializers.ValidationError(errors)
            attrs["durationMinutes"] = attrs["distanceKm"] = None
        else:
            if not attrs.get("durationMinutes") and not attrs.get("distanceKm"):
                raise serializers.ValidationError({"durationMinutes": ["Give a duration or a distance."]})
            attrs["sets"] = attrs["reps"] = attrs["weightKg"] = None
        return attrs


def _note():
    return serializers.CharField(max_length=NOTE_LIMIT, required=False, allow_blank=True, trim_whitespace=True)


# PUT /api/coaching/pt-sessions/<id>/log - the whole log; exercises replace the old list.
class SessionLogSerializer(serializers.Serializer):
    exercises = ExerciseSerializer(many=True, required=False)
    subjective = _note()
    objective = _note()
    assessment = _note()
    plan = _note()
    bodyWeightKg = serializers.DecimalField(
        max_digits=5, decimal_places=1, required=False, allow_null=True,
        validators=[_range("Body weight", Decimal("20"), Decimal("350"), " kg")],
    )
    sessionRpe = serializers.IntegerField(required=False, allow_null=True, validators=[_range("Session effort", 1, 10)])

    def validate_exercises(self, value):
        if len(value) > MAX_EXERCISES:
            raise serializers.ValidationError(f"Up to {MAX_EXERCISES} exercises per session.")
        return value

    def validate(self, attrs):
        notes = [attrs.get(f, "") for f in ("subjective", "objective", "assessment", "plan")]
        if not attrs.get("exercises") and not any(notes) and attrs.get("bodyWeightKg") is None:
            raise serializers.ValidationError("Add at least one exercise or a note - an empty log tells nobody anything.")
        return attrs


# POST /api/coaching/clients/<id>/goals and PATCH /api/coaching/goals/<id>.
class GoalSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ClientGoal.Kind.choices)
    title = serializers.CharField(max_length=120, required=False, allow_blank=True, trim_whitespace=True)
    exercise = serializers.CharField(max_length=80, required=False, allow_blank=True)
    targetValue = serializers.DecimalField(max_digits=6, decimal_places=1, required=False, allow_null=True)
    targetDate = serializers.DateField()
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, trim_whitespace=True)
    status = serializers.ChoiceField(choices=ClientGoal.Status.choices, required=False)

    def validate_targetDate(self, value):
        today = timezone.localdate()
        # A goal being edited may keep a date that has passed (it's then overdue).
        if self.instance is None and value <= today:
            raise serializers.ValidationError("Pick a date in the future.")
        if value > today + timedelta(days=GOAL_HORIZON_DAYS):
            raise serializers.ValidationError("Keep goals within two years - set a nearer milestone.")
        return value

    def validate(self, attrs):
        goal = self.instance
        kind = attrs.get("kind", goal.kind if goal else None)
        exercise = " ".join(attrs.get("exercise", goal.exercise if goal else "").split())
        target = attrs.get("targetValue", goal.target_value if goal else None)
        title = attrs.get("title", goal.title if goal else "")
        errors = {}
        if kind == ClientGoal.Kind.STRENGTH:
            if not exercise:
                errors["exercise"] = ["Which exercise?"]
            if target is None or not Decimal("1") <= target <= Decimal("500"):
                errors["targetValue"] = ["Give the target 1-rep max, between 1 and 500 kg."]
        elif kind == ClientGoal.Kind.BODY_WEIGHT:
            if target is None or not Decimal("20") <= target <= Decimal("350"):
                errors["targetValue"] = ["Give the target body weight, between 20 and 350 kg."]
            exercise = ""
        else:
            if not title:
                errors["title"] = ["Describe the goal, e.g. \"Run 5 km without stopping\"."]
            exercise, target = "", None
        if errors:
            raise serializers.ValidationError(errors)
        attrs["exercise"], attrs["targetValue"] = exercise, target
        if not title:
            attrs["title"] = (
                f"{exercise} {target.normalize():f} kg (estimated 1-rep max)" if kind == ClientGoal.Kind.STRENGTH
                else f"Reach {target.normalize():f} kg body weight"
            )
        return attrs
