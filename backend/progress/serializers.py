from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from .models import EXERCISES, BodyMetric, WorkoutEntry

# How far back an entry can be dated - enough to back-fill a notebook, not a typo'd 1926.
OLDEST_DAYS = 2 * 365


def _check_date(value):
    today = timezone.localdate()
    if value > today:
        raise serializers.ValidationError("That date is in the future.")
    if value < today - timedelta(days=OLDEST_DAYS):
        raise serializers.ValidationError("That's more than two years ago.")
    return value


def _range(name, low, high, unit=""):
    def check(value):
        if value is not None and not low <= value <= high:
            raise serializers.ValidationError(f"{name} should be between {low} and {high}{unit}.")
        return value
    return check


class WorkoutSerializer(serializers.ModelSerializer):
    date = serializers.DateField(source="performed_on", validators=[_check_date])
    exercise = serializers.CharField(max_length=80)
    kind = serializers.ChoiceField(choices=WorkoutEntry.Kind.choices, required=False)
    sets = serializers.IntegerField(required=False, allow_null=True, validators=[_range("Sets", 1, 20)])
    reps = serializers.IntegerField(required=False, allow_null=True, validators=[_range("Reps", 1, 100)])
    weightKg = serializers.DecimalField(
        source="weight_kg", max_digits=5, decimal_places=1, required=False, allow_null=True,
        validators=[_range("Weight", Decimal("0"), Decimal("500"), " kg")],
    )
    durationMinutes = serializers.IntegerField(
        source="duration_minutes", required=False, allow_null=True, validators=[_range("Duration", 1, 600, " minutes")],
    )
    distanceKm = serializers.DecimalField(
        source="distance_km", max_digits=5, decimal_places=2, required=False, allow_null=True,
        validators=[_range("Distance", Decimal("0.1"), Decimal("200"), " km")],
    )
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)

    class Meta:
        model = WorkoutEntry
        fields = ["id", "date", "exercise", "kind", "sets", "reps", "weightKg", "durationMinutes", "distanceKm", "note"]

    def validate(self, attrs):
        current = self.instance
        merged = {f: getattr(current, f) for f in ("exercise", "kind", "sets", "reps", "duration_minutes", "distance_km")} if current else {}
        merged.update(attrs)
        exercise = " ".join(str(merged.get("exercise", "")).split())
        if not exercise:
            raise serializers.ValidationError({"exercise": ["Pick or type an exercise."]})
        # A listed exercise has a known kind; a free-text one needs it said (default strength).
        kind = EXERCISES.get(exercise) or merged.get("kind") or WorkoutEntry.Kind.STRENGTH
        attrs["exercise"], attrs["kind"] = exercise, kind
        errors = {}
        if kind == WorkoutEntry.Kind.STRENGTH:
            if not merged.get("sets"):
                errors["sets"] = ["How many sets?"]
            if not merged.get("reps"):
                errors["reps"] = ["How many reps per set?"]
            attrs.update(duration_minutes=None, distance_km=None)
        else:
            if not merged.get("duration_minutes") and not merged.get("distance_km"):
                errors["durationMinutes"] = ["Give a duration or a distance."]
            attrs.update(sets=None, reps=None, weight_kg=None)
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class BodyMetricSerializer(serializers.ModelSerializer):
    date = serializers.DateField(source="measured_on", validators=[_check_date])
    weightKg = serializers.DecimalField(
        source="weight_kg", max_digits=5, decimal_places=1, validators=[_range("Body weight", Decimal("20"), Decimal("350"), " kg")],
    )
    bodyFatPercent = serializers.DecimalField(
        source="body_fat_percent", max_digits=4, decimal_places=1, required=False, allow_null=True,
        validators=[_range("Body fat", Decimal("2"), Decimal("70"), "%")],
    )
    waistCm = serializers.DecimalField(
        source="waist_cm", max_digits=5, decimal_places=1, required=False, allow_null=True,
        validators=[_range("Waist", Decimal("30"), Decimal("250"), " cm")],
    )
    chestCm = serializers.DecimalField(
        source="chest_cm", max_digits=5, decimal_places=1, required=False, allow_null=True,
        validators=[_range("Chest", Decimal("30"), Decimal("250"), " cm")],
    )
    hipsCm = serializers.DecimalField(
        source="hips_cm", max_digits=5, decimal_places=1, required=False, allow_null=True,
        validators=[_range("Hips", Decimal("30"), Decimal("250"), " cm")],
    )
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)

    class Meta:
        model = BodyMetric
        fields = ["id", "date", "weightKg", "bodyFatPercent", "waistCm", "chestCm", "hipsCm", "note"]

    def validate(self, attrs):
        member = self.context["member"]
        day = attrs.get("measured_on", self.instance.measured_on if self.instance else None)
        clash = BodyMetric.objects.filter(member=member, measured_on=day)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError({"date": ["You already logged metrics that day - edit that entry instead."]})
        return attrs
