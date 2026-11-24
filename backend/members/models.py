import secrets

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, models, transaction
from django.utils import timezone

# Easy to read out loud/type in: no 0/O or 1/I, which look alike on a
# handwritten receipt or a phone screen.
REFERRAL_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
REFERRAL_CODE_LENGTH = 6


def generate_referral_code():
    return "".join(secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(REFERRAL_CODE_LENGTH))


class Member(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "Active", "Active"
        # Also the status a member is moved to automatically when they have
        # no valid subscription - it expired, or they never paid for one
        # (see refresh_expiry_status and the lazy sweep in views.py). There's
        # no separate "Expired" status; only a payment makes them Active again.
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

    # Cached "when does their current subscription lapse" - denormalized
    # from their latest billing.Payment (see Payment.record()) so reads
    # here never need to join/query payments. Null for members who've
    # never had a payment recorded (e.g. seeded demo members) - they have
    # no valid subscription, so they read as Frozen until they pay.
    subscription_expires_at = models.DateField(null=True, blank=True)

    # Login credentials. Null for members registered as a walk-in by a
    # receptionist (RegisterMemberForm never sets these) - only a member who
    # self-signed-up through MemberSignupPage has an account they can log
    # into. Giving walk-in members a way to activate their own login later
    # (e.g. a "set your password" email link) is a separate future story.
    username = models.CharField(max_length=60, unique=True, null=True, blank=True)
    password_hash = models.CharField(max_length=255, null=True, blank=True)

    # Which access card / check-in QR code is the current one. It's signed
    # into the code (members/qr.py), so reissuing a card - bumping this -
    # makes every earlier code stop working.
    access_card_number = models.PositiveIntegerField(default=1)

    # User story: "As a member, I want to earn loyalty points for attending
    # sessions and referring friends, so that my consistency is rewarded."
    #
    # A short code every member gets, whichever way they joined (walk-in or
    # online) - theirs to hand to a friend, who enters it as "referralCode"
    # on their own registration (see MemberCreateSerializer/
    # MemberSignupSerializer). Generated once, on creation, by save() below;
    # never blank for a member created since this feature (see the
    # 0008 data migration for members from before it).
    referral_code = models.CharField(max_length=8, unique=True)

    # SCRUM-43: optional, for the "age range" segment filter. Members
    # without one on file never match an age filter. (Opting out of
    # marketing is the existing "offers" notification setting.)
    date_of_birth = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        if self.referral_code:
            return super().save(*args, **kwargs)
        # Generate-and-retry rather than check-then-create: two requests
        # creating a member at the same instant could otherwise both see
        # the same "unused" code free and collide on the unique constraint
        # - this just tries again with a fresh one when that happens.
        for _ in range(20):
            self.referral_code = generate_referral_code()
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                continue
        raise RuntimeError("Could not generate a unique referral code.")

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)

    # Valid through the end of its expiry date.
    def has_valid_subscription(self):
        return self.subscription_expires_at is not None and self.subscription_expires_at >= timezone.localdate()

    # Moves an "Active" member with no valid subscription to Frozen, right
    # now, for this one member - the single-row counterpart to the bulk
    # "_freeze_lapsed_members" sweep in members/views.py. Used anywhere a
    # single member's status needs to be trustworthy in the moment (member
    # detail, billing, the member's own login, and check-in - letting
    # someone in on a stale Active status would defeat "control entry").
    def refresh_expiry_status(self):
        if self.status == Member.Status.ACTIVE and not self.has_valid_subscription():
            self.status = Member.Status.FROZEN
            self.save(update_fields=["status"])

    def __str__(self):
        return f"{self.name} ({self.branch})"


# User story (SCRUM-83): "As a member, I want to sign a digital waiver and
# health disclaimer during signup, so that the gym has liability
# protection on file before I start training."
#
# One-to-one with Member. Both signup paths (walk-in registration and
# online signup) create the Member and its Waiver in the same transaction
# and refuse to save either unless both boxes are ticked and the typed
# signature matches the member's name, so every member created since this
# feature has liability protection on file. A member without a Waiver row
# shows as "Not on file".
#
# Original design: Ali's waiver PR (#3).
class Waiver(models.Model):
    class SignedVia(models.TextChoices):
        ONLINE = "Online signup", "Online signup"
        FRONT_DESK = "Front desk", "Front desk"

    member = models.OneToOneField(Member, on_delete=models.CASCADE, related_name="waiver")
    signature_name = models.CharField(max_length=150)
    health_disclaimer_accepted = models.BooleanField(default=False)
    liability_waiver_accepted = models.BooleanField(default=False)
    # Which wording was agreed to - see members/waiver.py.
    waiver_version = models.CharField(max_length=20)
    signed_via = models.CharField(max_length=20, choices=SignedVia.choices)
    # The receptionist at the desk for a walk-in signature; null online.
    witnessed_by = models.ForeignKey(
        "administration.StaffAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    signed_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Waiver for {self.member.name} ({self.signed_at:%Y-%m-%d})"


# User story: "As a receptionist, I want to reissue lost access cards or QR
# codes, so that I can resolve access issues without escalating to a manager."
#
# One row per replacement card: card_number is the card it issued, and the
# card before it stopped working at that moment. The original card (number
# 1, issued at sign-up) has no row.
class AccessCardReissue(models.Model):
    class Reason(models.TextChoices):
        LOST = "Lost", "Lost"
        STOLEN = "Stolen", "Stolen"
        DAMAGED = "Damaged", "Damaged"
        OTHER = "Other", "Other"

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="card_reissues")
    card_number = models.PositiveIntegerField()
    reason = models.CharField(max_length=20, choices=Reason.choices)
    note = models.CharField(max_length=200, blank=True)
    reissued_by = models.ForeignKey(
        "administration.StaffAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    reissued_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-reissued_at", "-id"]

    def __str__(self):
        return f"Card {self.card_number} for {self.member.name} ({self.reason})"
