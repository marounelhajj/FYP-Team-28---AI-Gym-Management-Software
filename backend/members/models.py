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

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.name} ({self.branch})"


# User story: "As a member, I want to sign a digital waiver and health
# disclaimer during signup, so that the gym has liability protection on
# file before I start training."
#
# One-to-one with Member: a member can't exist in the system without a
# signed waiver, because MemberCreateSerializer creates both together in
# one transaction and requires both acknowledgments to be True. That's
# what makes "liability protection on file" true by construction rather
# than a checkbox someone could leave unticked.
class Waiver(models.Model):
    member = models.OneToOneField(Member, on_delete=models.CASCADE, related_name="waiver")
    signature_name = models.CharField(max_length=150)
    health_disclaimer_accepted = models.BooleanField(default=False)
    liability_waiver_accepted = models.BooleanField(default=False)
    signed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Waiver for {self.member.name} ({self.signed_at:%Y-%m-%d})"
