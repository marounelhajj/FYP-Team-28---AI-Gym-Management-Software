from django.db import models
from django.utils import timezone

from members.models import Member

# User story: "As a coach, I want to view a client's health restrictions and
# injuries before starting a session, so that I can adapt the workout safely."
#
# The member records their own injuries, medical conditions and restrictions
# in the app; nobody else can add or change them. The coach of a class or
# private session they've booked can read them (healthnotes/access.py) - not
# the front desk, not managers. They're in the member's data export and are
# erased with the member (members/privacy.py).


class HealthNote(models.Model):
    class Kind(models.TextChoices):
        INJURY = "Injury", "Injury"
        CONDITION = "Medical condition", "Medical condition"
        RESTRICTION = "Restriction", "Other restriction"

    class BodyArea(models.TextChoices):
        NECK = "Neck", "Neck"
        SHOULDER = "Shoulder", "Shoulder"
        ARM = "Arm / elbow", "Arm / elbow"
        WRIST = "Wrist / hand", "Wrist / hand"
        BACK = "Back", "Back"
        CHEST = "Chest", "Chest"
        HIP = "Hip", "Hip"
        KNEE = "Knee", "Knee"
        LEG = "Leg", "Leg"
        ANKLE = "Ankle / foot", "Ankle / foot"
        HEART = "Heart / breathing", "Heart / breathing"
        GENERAL = "General", "General / whole body"

    # How much it limits training - what the coach scans for first.
    class Severity(models.TextChoices):
        MILD = "Mild", "Mild - train normally, with care"
        MODERATE = "Moderate", "Moderate - some exercises need adapting"
        SEVERE = "Severe", "Severe - avoid loading it"

    class Status(models.TextChoices):
        ACTIVE = "Active", "Active"
        RESOLVED = "Resolved", "Recovered"

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="health_notes")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    body_area = models.CharField(max_length=20, choices=BodyArea.choices, default=BodyArea.GENERAL)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    # e.g. "Torn ACL, left knee" and "No jumping or deep squats until January".
    title = models.CharField(max_length=80)
    details = models.CharField(max_length=500, blank=True)
    since = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    resolved_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-updated_at", "-id"]
        indexes = [models.Index(fields=["member", "status"], name="health_note_member_status_idx")]

    def __str__(self):
        return f"{self.member.name}: {self.title} ({self.status})"


# When the member last confirmed their health information is complete and
# current - by adding or changing a note, or by saying there's nothing (else)
# to declare. No row means they've never filled it in, which a coach must be
# able to tell apart from "nothing to declare".
class HealthDeclaration(models.Model):
    member = models.OneToOneField(Member, on_delete=models.CASCADE, related_name="health_declaration")
    reviewed_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.member.name} reviewed {self.reviewed_at:%Y-%m-%d}"
