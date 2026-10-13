from django.contrib.auth.hashers import make_password
from django.db import models


class Member(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "Active", "Active"
        FROZEN = "Frozen", "Frozen"
        CANCELLED = "Cancelled", "Cancelled"

    class Branch(models.TextChoices):
        HAMRA = "Hamra", "Hamra"
        ACHRAFIEH = "Achrafieh", "Achrafieh"
        JNAH = "Jnah", "Jnah"
        ZALKA = "Zalka", "Zalka"

    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=30)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    branch = models.CharField(max_length=30, choices=Branch.choices)
    # The name of a plans.MembershipPlan. Not a fixed choice list any more:
    # the General Manager defines plans at runtime (SCRUM-49), so the
    # serializers validate new values against the active plans instead.
    membership_plan = models.CharField(max_length=60, default="Basic")
    join_date = models.DateField()

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

    def __str__(self):
        return f"{self.name} ({self.branch})"
