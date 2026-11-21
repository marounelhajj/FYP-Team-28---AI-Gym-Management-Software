from rest_framework import serializers

from billing.models import Payment
from plans.models import MembershipPlan

from .access import door_access
from .models import AccessCardReissue, Member, Waiver
from .waiver import WAIVER_VERSION


# Shared by walk-in registration and online signup: a new member can only
# join a plan the General Manager currently sells (active MembershipPlan).
# Matching is case-insensitive and the plan's canonical name is stored.
def validate_active_plan_name(value):
    plan = MembershipPlan.objects.filter(name__iexact=(value or "").strip(), is_active=True).first()
    if plan is None:
        raise serializers.ValidationError("Choose one of the membership plans currently on offer.")
    return plan.name


class WaiverSerializer(serializers.ModelSerializer):
    signatureName = serializers.CharField(source="signature_name")
    waiverVersion = serializers.CharField(source="waiver_version")
    signedVia = serializers.CharField(source="signed_via")
    witnessedBy = serializers.CharField(source="witnessed_by.full_name", default=None)
    signedAt = serializers.DateTimeField(source="signed_at", format="%Y-%m-%d %H:%M")

    class Meta:
        model = Waiver
        fields = ["signatureName", "waiverVersion", "signedVia", "witnessedBy", "signedAt"]


# Shared by walk-in registration and online signup (SCRUM-83): the new
# member reads the waiver and health disclaimer (GET /api/members/waiver),
# ticks both boxes and types their full name as a signature. Registration
# fails - no Member row at all - unless all three are given and the
# signature matches the name on the form.
class WaiverSignatureFields(serializers.Serializer):
    liabilityWaiverAccepted = serializers.BooleanField()
    healthDisclaimerAccepted = serializers.BooleanField()
    signatureName = serializers.CharField(max_length=150)

    def validate_liabilityWaiverAccepted(self, value):
        if not value:
            raise serializers.ValidationError("The liability waiver must be accepted to register.")
        return value

    def validate_healthDisclaimerAccepted(self, value):
        if not value:
            raise serializers.ValidationError("The health disclaimer must be accepted to register.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        typed = " ".join(attrs["signatureName"].split()).casefold()
        if typed != " ".join(attrs.get("name", "").split()).casefold():
            raise serializers.ValidationError(
                {"signatureName": ["Type your full name exactly as entered above to sign."]}
            )
        return attrs

    @staticmethod
    def pop_signature(validated_data):
        return {
            "liability_waiver_accepted": validated_data.pop("liabilityWaiverAccepted"),
            "health_disclaimer_accepted": validated_data.pop("healthDisclaimerAccepted"),
            "signature_name": " ".join(validated_data.pop("signatureName").split()),
            "waiver_version": WAIVER_VERSION,
        }


# PATCH /api/members/me - a member editing their own contact info.
#
# User story: "As a member, I want to update my saved payment method and
# personal profile information myself in the app, so that I don't need to
# visit the front desk for routine changes."
#
# Deliberately narrow to name/email/phone: branch, plan, and status change
# through staff/billing flows (a plan or branch switch has pricing
# implications a member shouldn't be able to trigger unsupervised).
class MemberProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Member
        fields = ["name", "email", "phone"]
        extra_kwargs = {
            "name": {"required": False},
            "email": {"required": False},
            "phone": {"required": False},
        }

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Name can't be blank.")
        return value

    def validate_phone(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Phone can't be blank.")
        return value


class MemberSerializer(serializers.ModelSerializer):
    membershipPlan = serializers.CharField(source="membership_plan")
    joinDate = serializers.DateField(source="join_date", format="%Y-%m-%d")
    subscriptionExpiresAt = serializers.DateField(source="subscription_expires_at", format="%Y-%m-%d", allow_null=True)

    class Meta:
        model = Member
        fields = [
            "id", "name", "email", "phone", "status", "branch", "membershipPlan",
            "joinDate", "subscriptionExpiresAt", "waiver", "doorAccess",
        ]

    # null for a member with no signed waiver on file.
    waiver = serializers.SerializerMethodField()
    # Whether their card opens the doors right now, and why not (members/access.py).
    doorAccess = serializers.SerializerMethodField()

    def get_waiver(self, obj):
        try:
            return WaiverSerializer(obj.waiver).data
        except Waiver.DoesNotExist:
            return None

    def get_doorAccess(self, obj):
        access = door_access(obj)
        return {
            "granted": access.granted,
            "reason": access.reason,
            "message": access.message,
            "validUntil": access.valid_until,
        }


# Used by POST /api/members to register a new walk-in member.
#
# User story: "As a receptionist, I want to register a new walk-in member's
# profile and membership plan, so that I can onboard new customers on the
# spot." Extended per: "As a receptionist, I want to process a new member's
# first payment during registration, so that their membership is activated
# immediately." - a walk-in registration now requires a payment and a
# subscription duration (1 Month / 1 Year), not just a profile; the
# payment is what the Active status and expiry date are conditioned on.
# The subscription does not auto-renew - see Payment.record() and the
# lazy "freeze lapsed members" sweep in views.py for how it lapses back to
# Frozen, and member_payment (POST /api/members/<id>/payments) for how an
# existing member repays to reactivate.
#
# status and joinDate are intentionally NOT accepted from the client: a
# freshly registered walk-in is always Active, and the join date is always
# "today" - both are set server-side in create() below. There is no
# paymentAmount field: the amount is looked up server-side by
# Payment.record() (billing.models.renewal_quote(), branch-aware) - the
# receptionist picks a plan, not a price.
class MemberCreateSerializer(WaiverSignatureFields, serializers.ModelSerializer):
    membershipPlan = serializers.CharField(source="membership_plan")
    paymentMethod = serializers.ChoiceField(choices=Payment.Method.choices)
    paymentDuration = serializers.ChoiceField(choices=Payment.Duration.choices)
    # A marketing offer code the new member gave (optional) - see
    # marketing.offers.check_signup_offer. Not a model field, so it's
    # popped out of validated_data in create() below.
    offerCode = serializers.CharField(max_length=40, required=False, allow_blank=True, write_only=True)
    # A referring member's loyalty.points referral code (optional, also
    # not a model field) - see validate()/create() below.
    referralCode = serializers.CharField(max_length=12, required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Member
        fields = [
            "name", "email", "phone", "branch", "membershipPlan", "paymentMethod", "paymentDuration",
            "offerCode", "referralCode",
            "liabilityWaiverAccepted", "healthDisclaimerAccepted", "signatureName",
        ]

    def validate_membershipPlan(self, value):
        return validate_active_plan_name(value)

    # Checked here (not just inside Payment.record()) so a bad code is
    # reported as a normal field error before anything is created - the
    # same code is re-checked, under a lock, when it's actually redeemed,
    # in case it was just claimed by someone else at another desk.
    def validate(self, attrs):
        attrs = super().validate(attrs)
        from marketing.offers import OfferError, check_signup_offer

        code = (attrs.get("offerCode") or "").strip()
        self._offer_campaign = None
        if code and "branch" in attrs:
            try:
                self._offer_campaign = check_signup_offer(code, attrs["branch"])
            except OfferError as error:
                raise serializers.ValidationError({"offerCode": [error.message]})

        # User story: "As a member, I want to earn loyalty points for
        # attending sessions and referring friends, so that my consistency
        # is rewarded." - looked up now so a typo'd code is reported as a
        # normal field error before anything is created, same reasoning as
        # offerCode above. Global, not branch-scoped: a member can refer a
        # friend to any branch.
        referral_code = (attrs.get("referralCode") or "").strip().upper()
        self._referrer = None
        if referral_code:
            self._referrer = Member.objects.filter(referral_code=referral_code).first()
            if self._referrer is None:
                raise serializers.ValidationError(
                    {"referralCode": [f'No member found with referral code "{referral_code}".']}
                )
        return attrs

    def create(self, validated_data):
        from django.db import transaction
        from django.utils import timezone

        payment_method = validated_data.pop("paymentMethod")
        payment_duration = validated_data.pop("paymentDuration")
        validated_data.pop("offerCode", None)
        validated_data.pop("referralCode", None)
        signature = self.pop_signature(validated_data)

        validated_data["join_date"] = timezone.now().date()

        # Member, its signed Waiver and its first Payment are created together, atomically:
        # if Payment.record() fails for any reason, the whole block rolls
        # back - including the member row - so nobody can ever observe a
        # member that exists without the payment that's supposed to
        # justify it. (The model's status default is technically "Active",
        # but that's never visible to another request/connection since it
        # never gets committed unless Payment.record() also succeeds.)
        with transaction.atomic():
            member = Member.objects.create(**validated_data)
            Waiver.objects.create(
                member=member, signed_via=Waiver.SignedVia.FRONT_DESK,
                witnessed_by=self.context.get("staff_account"), **signature,
            )
            payment = Payment.record(
                member, member.membership_plan, payment_method, payment_duration,
                note="First payment at registration", recorded_by=self.context.get("staff_account"),
                offer=self._offer_campaign,
            )
            if self._referrer:
                from loyalty.points import award_referral

                award_referral(self._referrer, member)
        # Stashed (not DB fields) so the view can include them in the
        # creation response/audit log without an extra query for what was
        # just done in this same request.
        member.first_payment = payment
        member.referred_by = self._referrer
        return member


# Used by POST /api/members/signup for self-service registration.
#
# User story: "As a prospective member, I want to browse membership plans
# and sign up online, so that I can join a branch without visiting in
# person first."
#
# Unlike a walk-in (MemberCreateSerializer above), a self-signup member
# sets their own username/password here and can log in immediately - but
# they're still not Active until they pay: a member's status is never
# Active without a recorded Payment, regardless of which of the two
# creation paths they came through, and the amount is likewise never
# client-supplied here either - see Payment.record() in billing/models.py.
class MemberSignupSerializer(WaiverSignatureFields, serializers.ModelSerializer):
    membershipPlan = serializers.CharField(source="membership_plan")
    password = serializers.CharField(write_only=True, min_length=8)
    paymentMethod = serializers.ChoiceField(choices=Payment.Method.choices)
    paymentDuration = serializers.ChoiceField(choices=Payment.Duration.choices)
    # validators=[] disables DRF's auto-generated UniqueValidator (attached
    # because username is unique=True on the model) so our own
    # validate_username message below is the one that actually fires.
    username = serializers.CharField(validators=[])
    # Same as MemberCreateSerializer.offerCode/referralCode above - optional,
    # not model fields, popped out of validated_data in create() below.
    offerCode = serializers.CharField(max_length=40, required=False, allow_blank=True, write_only=True)
    referralCode = serializers.CharField(max_length=12, required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Member
        fields = [
            "name", "email", "phone", "branch", "membershipPlan", "username", "password",
            "paymentMethod", "paymentDuration", "offerCode", "referralCode",
            "liabilityWaiverAccepted", "healthDisclaimerAccepted", "signatureName",
        ]

    def validate_membershipPlan(self, value):
        return validate_active_plan_name(value)

    def validate_username(self, value):
        if Member.objects.filter(username=value).exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate_email(self, value):
        if Member.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    # Same reasoning as MemberCreateSerializer.validate() above.
    def validate(self, attrs):
        attrs = super().validate(attrs)
        from marketing.offers import OfferError, check_signup_offer

        code = (attrs.get("offerCode") or "").strip()
        self._offer_campaign = None
        if code and "branch" in attrs:
            try:
                self._offer_campaign = check_signup_offer(code, attrs["branch"])
            except OfferError as error:
                raise serializers.ValidationError({"offerCode": [error.message]})

        # User story: "As a member, I want to earn loyalty points for
        # attending sessions and referring friends, so that my consistency
        # is rewarded." - looked up now so a typo'd code is reported as a
        # normal field error before anything is created, same reasoning as
        # offerCode above. Global, not branch-scoped: a member can refer a
        # friend to any branch.
        referral_code = (attrs.get("referralCode") or "").strip().upper()
        self._referrer = None
        if referral_code:
            self._referrer = Member.objects.filter(referral_code=referral_code).first()
            if self._referrer is None:
                raise serializers.ValidationError(
                    {"referralCode": [f'No member found with referral code "{referral_code}".']}
                )
        return attrs

    def create(self, validated_data):
        from django.db import transaction
        from django.utils import timezone

        password = validated_data.pop("password")
        payment_method = validated_data.pop("paymentMethod")
        payment_duration = validated_data.pop("paymentDuration")
        validated_data.pop("offerCode", None)
        validated_data.pop("referralCode", None)
        signature = self.pop_signature(validated_data)

        validated_data["join_date"] = timezone.now().date()
        member = Member(**validated_data)
        member.set_password(password)

        # Same atomic member+payment pairing as MemberCreateSerializer
        # above - see its comment for why.
        with transaction.atomic():
            member.save()
            Waiver.objects.create(member=member, signed_via=Waiver.SignedVia.ONLINE, **signature)
            payment = Payment.record(
                member, member.membership_plan, payment_method, payment_duration,
                note="First payment at signup", offer=self._offer_campaign,
            )
            if self._referrer:
                from loyalty.points import award_referral

                award_referral(self._referrer, member)
        member.first_payment = payment
        member.referred_by = self._referrer
        return member


class AccessCardReissueSerializer(serializers.ModelSerializer):
    cardNumber = serializers.IntegerField(source="card_number")
    reissuedBy = serializers.CharField(source="reissued_by.full_name", default=None)
    reissuedAt = serializers.DateTimeField(source="reissued_at", format="%Y-%m-%d %H:%M")

    class Meta:
        model = AccessCardReissue
        fields = ["cardNumber", "reason", "note", "reissuedBy", "reissuedAt"]


# POST /api/members/<id>/access-card. identityConfirmed is the receptionist
# confirming they checked the member's photo ID - the safeguard that lets a
# card be reissued at the desk without a manager.
class AccessCardReissueCreateSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=AccessCardReissue.Reason.choices)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    identityConfirmed = serializers.BooleanField()

    def validate_identityConfirmed(self, value):
        if not value:
            raise serializers.ValidationError("Check the member's photo ID before reissuing their card.")
        return value

    def validate(self, attrs):
        attrs["note"] = " ".join(attrs.get("note", "").split())
        if attrs["reason"] == AccessCardReissue.Reason.OTHER and not attrs["note"]:
            raise serializers.ValidationError({"note": ["Say why the card is being reissued."]})
        return attrs
