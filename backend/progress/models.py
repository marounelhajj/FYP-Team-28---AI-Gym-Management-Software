from django.db import models

from members.models import Member

# User story (SCRUM-60): "As a member, I want to log my own workouts and body
# metrics between sessions, so that my coach and the AI system have
# up-to-date data to base recommendations on."
#
# Both are the member's own data: they add, edit and delete them; their
# assigned coach can only read them (progress/views.py), and the SCRUM-62
# export/deletion flow includes and erases them. New entries are also written
# to the AI training-data log (SCRUM-73). Units are always kg, cm and km.

# Pick-list for the workout form (free text is allowed too). The kind decides
# which fields matter: sets/reps/weight for strength, duration/distance for cardio.
EXERCISES = {
    "Bench press": "strength", "Squat": "strength", "Deadlift": "strength", "Overhead press": "strength",
    "Barbell row": "strength", "Pull-up": "strength", "Lat pulldown": "strength", "Leg press": "strength",
    "Bicep curl": "strength", "Tricep extension": "strength", "Lunges": "strength", "Plank": "strength",
    "Running": "cardio", "Treadmill": "cardio", "Cycling": "cardio", "Rowing machine": "cardio",
    "Elliptical": "cardio", "Swimming": "cardio", "Jump rope": "cardio", "Stair climber": "cardio",
}


class WorkoutEntry(models.Model):
    class Kind(models.TextChoices):
        STRENGTH = "strength", "Strength"
        CARDIO = "cardio", "Cardio"

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="workouts")
    performed_on = models.DateField()
    exercise = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    sets = models.PositiveSmallIntegerField(null=True, blank=True)
    reps = models.PositiveSmallIntegerField(null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    distance_km = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-performed_on", "-id"]

    def __str__(self):
        return f"{self.member} {self.exercise} on {self.performed_on}"


class BodyMetric(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="body_metrics")
    measured_on = models.DateField()
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1)
    body_fat_percent = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    waist_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    chest_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    hips_cm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-measured_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["member", "measured_on"], name="one_body_metric_per_member_per_day"),
        ]

    def __str__(self):
        return f"{self.member} {self.weight_kg} kg on {self.measured_on}"
