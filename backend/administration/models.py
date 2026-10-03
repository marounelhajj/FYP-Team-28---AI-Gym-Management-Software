from django.contrib.auth.hashers import make_password
from django.db import models

# The fixed set of permission keys a role can be granted. Kept as a plain
# list (rather than a DB table) for the same reason Member uses TextChoices
# for status/branch/plan: it's a small, code-owned set of values, so the
# "define roles with specific permission sets" UI can render checkboxes
# without a separate CRUD surface just for permissions themselves.
PERMISSION_CHOICES = [
    ("manage_members", "Manage members"),
    ("manage_staff_accounts", "Manage staff accounts"),
    ("manage_roles", "Manage roles & permissions"),
    ("manage_class_schedule", "Manage class schedule"),
    ("manage_billing", "Manage billing & payments"),
    ("view_financial_reports", "View financial reports"),
    ("manage_marketing_campaigns", "Manage marketing campaigns"),
    ("view_audit_log", "View audit log"),
]
PERMISSION_KEYS = {key for key, _ in PERMISSION_CHOICES}


class Role(models.Model):
    name = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=255, blank=True)
    permissions = models.JSONField(default=list)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class StaffAccount(models.Model):
    class JobTitle(models.TextChoices):
        SYSTEM_ADMINISTRATOR = "System Administrator", "System Administrator"
        GENERAL_MANAGER = "General Manager", "General Manager"
        BRANCH_MANAGER = "Branch Manager", "Branch Manager"
        RECEPTIONIST = "Receptionist", "Receptionist"
        COACH = "Coach", "Coach"
        MARKETING_STAFF = "Marketing Staff", "Marketing Staff"

    full_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=60, unique=True)
    password_hash = models.CharField(max_length=255)
    job_title = models.CharField(max_length=30, choices=JobTitle.choices)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="staff_accounts")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)

    def __str__(self):
        status = "active" if self.is_active else "deactivated"
        return f"{self.full_name} ({self.username}, {status})"
