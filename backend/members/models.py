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
