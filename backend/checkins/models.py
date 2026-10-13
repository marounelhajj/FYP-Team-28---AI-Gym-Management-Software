from django.db import models


class CheckIn(models.Model):
    class Result(models.TextChoices):
        ALLOWED = "Allowed", "Allowed"
        DENIED = "Denied", "Denied"

    member = models.ForeignKey("members.Member", on_delete=models.CASCADE, related_name="check_ins")
    result = models.CharField(max_length=10, choices=Result.choices)
    # The reason entry was refused (e.g. "Frozen", "Cancelled", "Already
    # checked in") - blank when result is Allowed.
    reason = models.CharField(max_length=30, blank=True)
    checked_in_at = models.DateTimeField(auto_now_add=True)
    # Null while the member is still inside - that's what makes a row an
    # "open session". Only ever set on an Allowed row, by checking out.
    checked_out_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-checked_in_at"]

    def __str__(self):
        return f"{self.member.name} - {self.result} @ {self.checked_in_at}"
