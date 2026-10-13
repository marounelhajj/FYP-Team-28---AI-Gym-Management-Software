from django.contrib.auth.hashers import make_password
from django.db import models


class Member(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "Active", "Active"
        # Also the status a member lapses into automatically once their
        # subscription_expires_at passes with no renewal (see the lazy
        # sweep in views.py) - there's no separate "Expired" status; a
        # lapsed/unpaid member reads the same as a staff-frozen one.
        FROZEN = "Frozen", "Frozen"
        CANCELLED = "Cancelled", "Cancelled"

    class Branch(models.TextChoices):
        HAMRA = "Hamra", "Hamra"
        ACHRAFIEH = "Achrafieh", "Achrafieh"
        JNAH = "Jnah", "Jnah"
        ZALKA = "Zalka", "Zalka"

    class Plan(models.TextChoices):
        BASIC = "Basic", "Basic"
        STANDARD = "Standard", "Standard"
        PREMIUM = "Premium", "Premium"

    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    branch = models.CharField(max_length=30, choices=Branch.choices)
    membership_plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.BASIC)
    join_date = models.DateField()

    # Cached "when does their current subscription lapse" - denormalized
    # from their latest billing.Payment (see Payment.record()) so reads
    # here never need to join/query payments. Null for members who've
    # never had a payment recorded (e.g. pre-existing seeded members from
    # before this feature existed).
    subscription_expires_at = models.DateField(null=True, blank=True)

    # Login credentials. Null for members registered as a walk-in by a
    # receptionist (RegisterMemberForm never sets these) - only a member who
    # self-signed-up through MemberSignupPage has an account they can log
    # into. Giving walk-in members a way to activate their own login later
    # (e.g. a "set your password" email link) is a separate future story.
    username = models.CharField(max_length=60, unique=True, null=True, blank=True)
    password_hash = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)

    # Flips a lapsed-but-still-"Active" member to Frozen, right now, for
    # this one member - the single-row counterpart to the bulk
    # "_freeze_lapsed_members" sweep in members/views.py. Used anywhere a
    # single member's status needs to be trustworthy in the moment
    # (member_detail, and check-in - letting someone in on a stale Active
    # status would defeat "control entry").
    def refresh_expiry_status(self):
        from django.utils import timezone

        if (
            self.status == Member.Status.ACTIVE
            and self.subscription_expires_at
            and self.subscription_expires_at < timezone.localdate()
        ):
            self.status = Member.Status.FROZEN
            self.save(update_fields=["status"])

    def __str__(self):
        return f"{self.name} ({self.branch})"
