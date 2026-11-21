from django.db import models
from django.db.models import Q
from django.utils import timezone

from classes.models import ClassBooking, PTSession
from members.models import Member

# User story: "As a member, I want to earn loyalty points for attending
# sessions and referring friends, so that my consistency is rewarded."
#
# One row per award, never edited once created - the member's balance
# (loyalty.points.balance) is always the sum of their rows, the same
# ledger-as-source-of-truth approach as billing.Payment and
# marketing.CampaignRedemption, rather than a cached counter that can drift.
#
# A row links back to exactly one of the three things that can earn
# points - a class booking, a PT session, or the new member referred -
# which also doubles as the "already paid out" guard (see the unique
# constraints below): settle_attendance() runs lazily and can see the same
# booking more than once, and a registration can only award its referral
# once.
class LoyaltyPointEntry(models.Model):
    class Reason(models.TextChoices):
        CLASS_ATTENDED = "ClassAttended", "Attended a class"
        PT_ATTENDED = "PTAttended", "Attended a private training session"
        REFERRAL = "Referral", "Referred a new member"

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="loyalty_entries")
    points = models.PositiveSmallIntegerField()
    reason = models.CharField(max_length=20, choices=Reason.choices)

    # Exactly one of these three is set, matching `reason` - which one
    # depends on how the points were earned.
    class_booking = models.ForeignKey(
        ClassBooking, on_delete=models.CASCADE, null=True, blank=True, related_name="+",
    )
    pt_session = models.ForeignKey(
        PTSession, on_delete=models.CASCADE, null=True, blank=True, related_name="+",
    )
    # The new member THIS member referred (not the referring member - see
    # `member` above). Set only for a Referral row.
    referred_member = models.ForeignKey(
        Member, on_delete=models.CASCADE, null=True, blank=True, related_name="+",
    )

    earned_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-earned_at", "-id"]
        constraints = [
            # One payout per booking/session/referral, however many times
            # the awarding code runs for it.
            models.UniqueConstraint(
                fields=["class_booking"], condition=Q(class_booking__isnull=False),
                name="one_loyalty_entry_per_class_booking",
            ),
            models.UniqueConstraint(
                fields=["pt_session"], condition=Q(pt_session__isnull=False),
                name="one_loyalty_entry_per_pt_session",
            ),
            models.UniqueConstraint(
                fields=["referred_member"], condition=Q(referred_member__isnull=False),
                name="one_loyalty_entry_per_referred_member",
            ),
        ]

    def __str__(self):
        return f"{self.member.name} +{self.points} ({self.reason})"
