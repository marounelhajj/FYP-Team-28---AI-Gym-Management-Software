from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from administration.models import StaffAccount
from members.models import Member

# User story: "As a branch manager, I want to view member feedback and
# complaints specific to my branch, so that I can address local service
# issues directly rather than waiting on a company wide report."
#
# Two ways in, for two different jobs:
#   * BranchSurvey - a short, measurable pulse: how likely the member is to
#     recommend the branch (Net Promoter Score, 0-10), five service areas
#     rated 1-5, and an optional comment. Can be anonymous to the manager.
#   * Complaint - a specific problem that needs an answer: a case the
#     branch's managers reply to and resolve, with the member told each step.
#
# The member link is kept even for anonymous surveys (it's what limits a
# member to one survey a month); the manager just never sees who it was.

AREAS = [
    ("cleanliness", "Cleanliness"),
    ("equipment", "Equipment"),
    ("staff", "Staff"),
    ("classes", "Classes"),
    ("atmosphere", "Crowding & atmosphere"),
]


def _area():
    return models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)],
    )


class BranchSurvey(models.Model):
    # Null once the member's data has been erased - the scores still count.
    member = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="branch_surveys")
    branch = models.CharField(max_length=30, choices=Member.Branch.choices, db_index=True)
    nps = models.PositiveSmallIntegerField(validators=[MaxValueValidator(10)])
    # 1 (very poor) to 5 (excellent); empty when the member skipped it (e.g. never takes classes).
    cleanliness = _area()
    equipment = _area()
    staff = _area()
    classes = _area()
    atmosphere = _area()
    comment = models.CharField(max_length=1000, blank=True)
    anonymous = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.branch} survey: NPS {self.nps} ({self.created_at:%Y-%m-%d})"


class Complaint(models.Model):
    class Category(models.TextChoices):
        EQUIPMENT = "Equipment", "Broken or missing equipment"
        CLEANLINESS = "Cleanliness", "Cleanliness"
        STAFF = "Staff", "Staff behaviour"
        CLASSES = "Classes", "Classes & coaching"
        CROWDING = "Crowding", "Crowding"
        BILLING = "Billing", "Billing & membership"
        SAFETY = "Safety", "Safety"
        OTHER = "Other", "Something else"

    class Status(models.TextChoices):
        OPEN = "Open", "Open"
        IN_PROGRESS = "In progress", "In progress"
        RESOLVED = "Resolved", "Resolved"

    member = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="complaints")
    branch = models.CharField(max_length=30, choices=Member.Branch.choices, db_index=True)
    category = models.CharField(max_length=20, choices=Category.choices)
    subject = models.CharField(max_length=120)
    description = models.CharField(max_length=2000)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    # Safety problems jump the queue.
    urgent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    # The first time staff answered the member - what the response target is measured on.
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.branch}: {self.subject} ({self.status})"


class ComplaintMessage(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="messages")
    author_staff = models.ForeignKey(StaffAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    author_member = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    body = models.CharField(max_length=1000)
    # A note between staff only - never shown to the member.
    internal = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Message on complaint {self.complaint_id}"
