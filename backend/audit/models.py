from django.db import models
from django.utils import timezone

# Permanent, append-only record of who did what (SCRUM-124).
#
# User story: "As a system administrator, I want sensitive actions to be
# written to an audit log automatically, so that there is a permanent record
# of who did what."
#
# Entries are written by audit.log.record() from the views that perform the
# action - never from the client - and can't be edited or deleted afterwards:
# AuditLog.save() refuses to update an existing row, and both the model and
# its queryset refuse delete()/update(). The actor's name, username and role
# are copied onto the row at the time of the action, so the record still
# reads correctly after that account is renamed, moved to another role, or
# deactivated.


class AuditLogImmutable(Exception):
    pass


class AuditLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AuditLogImmutable("Audit log entries can't be changed.")

    def delete(self):
        raise AuditLogImmutable("Audit log entries can't be deleted.")


class AuditLog(models.Model):
    class Action(models.TextChoices):
        # Staff sign-in and two-factor
        STAFF_LOGIN = "staff.login", "Staff signed in"
        STAFF_LOGIN_FAILED = "staff.login_failed", "Failed staff sign-in"
        STAFF_2FA_LOCKED = "staff.2fa_locked", "Staff locked out (two-factor)"
        STAFF_2FA_RESET = "staff.2fa_reset", "Two-factor reset"
        # Staff accounts and roles
        STAFF_CREATED = "staff.created", "Staff account created"
        STAFF_UPDATED = "staff.updated", "Staff account edited"
        STAFF_DEACTIVATED = "staff.deactivated", "Staff account deactivated"
        STAFF_REACTIVATED = "staff.reactivated", "Staff account reactivated"
        ROLE_CREATED = "role.created", "Role created"
        ROLE_UPDATED = "role.updated", "Role edited"
        # Plans and pricing
        PLAN_CREATED = "plan.created", "Membership plan created"
        PLAN_UPDATED = "plan.updated", "Membership plan edited"
        PROMOTION_CREATED = "promotion.created", "Branch promotion created"
        PROMOTION_UPDATED = "promotion.updated", "Branch promotion edited"
        # Members and billing
        MEMBER_REGISTERED = "member.registered", "Walk-in member registered"
        MEMBER_SIGNED_UP = "member.signed_up", "Member signed up online"
        MEMBER_PROFILE_UPDATED = "member.profile_updated", "Member profile edited"
        MEMBER_FROZEN = "member.frozen", "Membership frozen"
        MEMBER_RESUMED = "member.resumed", "Membership resumed"
        MEMBER_CANCELLED = "member.cancelled", "Membership cancelled"
        PAYMENT_RECORDED = "payment.recorded", "Payment recorded"
        PAYMENT_METHOD_UPDATED = "payment_method.updated", "Payment method changed"
        ACCESS_CARD_REISSUED = "access_card.reissued", "Access card reissued"
        # Privacy requests (SCRUM-62)
        MEMBER_DATA_EXPORTED = "member.data_exported", "Member data exported"
        MEMBER_DATA_DELETED = "member.data_deleted", "Member data deleted"
        # Front desk
        CHECKIN_FLAGGED = "checkin.flagged", "Check-in attempt flagged"
        CHECKIN_FLAG_RESOLVED = "checkin.flag_resolved", "Check-in flag resolved"
        # Door readers
        DOOR_CREATED = "door.created", "Door reader added"
        DOOR_UPDATED = "door.updated", "Door reader edited"
        DOOR_KEY_ROTATED = "door.key_rotated", "Door reader key replaced"
        # Retail (point of sale)
        RETAIL_SALE = "retail.sale", "Retail sale"
        RETAIL_SALE_VOIDED = "retail.sale_voided", "Retail sale voided"
        RETAIL_PRODUCT_CREATED = "retail.product_created", "Retail product added"
        RETAIL_PRODUCT_UPDATED = "retail.product_updated", "Retail product edited"
        RETAIL_STOCK_ADJUSTED = "retail.stock_adjusted", "Retail stock changed"
        # Class schedule
        CLASS_CREATED = "class.created", "Class scheduled"
        CLASS_UPDATED = "class.updated", "Class edited"
        CLASS_CANCELLED = "class.cancelled", "Class cancelled"
        CLASS_TYPE_CREATED = "class.type_created", "Class type added"
        CLASS_TYPE_UPDATED = "class.type_updated", "Class type edited"
        PT_HOURS_ADDED = "class.pt_hours_added", "Private training hours added"
        PT_HOURS_REMOVED = "class.pt_hours_removed", "Private training hours removed"
        PT_SESSION_CANCELLED = "class.pt_session_cancelled", "Private training session cancelled by staff"
        # The log itself (SCRUM-126) - who took a copy of which entries.
        AUDIT_LOG_EXPORTED = "audit_log.exported", "Audit log exported"

    class ActorType(models.TextChoices):
        STAFF = "Staff", "Staff"
        MEMBER = "Member", "Member"
        # Nobody signed in, e.g. a failed login with an unknown username.
        ANONYMOUS = "Anonymous", "Anonymous"

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    action = models.CharField(max_length=40, choices=Action.choices, db_index=True)

    actor_type = models.CharField(max_length=10, choices=ActorType.choices)
    actor_staff = models.ForeignKey(
        "administration.StaffAccount", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    actor_member = models.ForeignKey(
        "members.Member", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    actor_name = models.CharField(max_length=150, blank=True)
    actor_username = models.CharField(max_length=60, blank=True)
    actor_role = models.CharField(max_length=60, blank=True)

    # What the action was done to, e.g. ("member", "42", "Lina Saad").
    target_type = models.CharField(max_length=30, blank=True)
    target_id = models.CharField(max_length=40, blank=True)
    target_label = models.CharField(max_length=200, blank=True)

    # The branch the action concerns (the member's, promotion's or staff
    # member's branch), falling back to the actor's own branch.
    branch = models.CharField(max_length=30, blank=True, db_index=True)

    summary = models.CharField(max_length=255)
    # Extra context: changed fields as {field: [old, new]}, a failure
    # reason, an amount... Never passwords, 2FA secrets or card numbers.
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["actor_staff", "created_at"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditLogImmutable("Audit log entries can't be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditLogImmutable("Audit log entries can't be deleted.")

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_username or self.actor_type}: {self.summary}"
