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
    ("manage_membership_plans", "Manage membership plans & pricing"),
    ("manage_branch_promotions", "Manage branch promotions"),
    ("view_financial_reports", "View financial reports"),
    ("manage_marketing_campaigns", "Manage marketing campaigns"),
    ("view_audit_log", "View audit log"),
    ("view_training_data", "View AI training data"),
    ("view_branch_headcount", "View live branch headcount"),
    ("view_all_branches", "See every branch (not just their own)"),
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

    # Mirrors members.Member.Branch - kept as its own copy (rather than a
    # shared import across apps) for the same reason job titles/permissions
    # are plain choices here: a small, code-owned set of values.
    class Branch(models.TextChoices):
        HAMRA = "Hamra", "Hamra"
        ACHRAFIEH = "Achrafieh", "Achrafieh"
        JNAH = "Jnah", "Jnah"
        ZALKA = "Zalka", "Zalka"

    full_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    username = models.CharField(max_length=60, unique=True)
    password_hash = models.CharField(max_length=255)
    job_title = models.CharField(max_length=30, choices=JobTitle.choices)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="staff_accounts")
    # Which branch this staff/trainer profile belongs to. Optional: a
    # System Administrator or General Manager may not be tied to a single
    # branch, while a Branch Manager, Receptionist, or Coach usually is.
    #
    # User story: "As a general manager, I want to add, edit, and remove
    # staff and trainer profiles at a branch, so that I can manage headcount
    # and certified training staff." ("remove" reuses the existing
    # deactivate/reactivate behavior below rather than a hard delete, so
    # history - e.g. past class assignments - isn't lost.)
    branch = models.CharField(max_length=30, choices=Branch.choices, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Two-factor sign-in (SCRUM-87). Every staff account must enroll an
    # authenticator app; two_factor_enabled stays False until the first
    # code is confirmed, and an administrator reset sets it back to False.
    # The secret is Fernet-encrypted (see totp.py) and never serialized.
    totp_secret_encrypted = models.TextField(blank=True, default="")
    two_factor_enabled = models.BooleanField(default=False)
    totp_last_used_step = models.BigIntegerField(null=True, blank=True)
    failed_2fa_attempts = models.PositiveSmallIntegerField(default=0)
    two_factor_locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)

    def __str__(self):
        status = "active" if self.is_active else "deactivated"
        return f"{self.full_name} ({self.username}, {status})"


# One-time recovery codes for a staff account's second factor. Only a hash
# is stored; the codes themselves are shown once, right after enrollment.
class StaffBackupCode(models.Model):
    account = models.ForeignKey(StaffAccount, on_delete=models.CASCADE, related_name="backup_codes")
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
