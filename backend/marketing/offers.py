import logging
import re
from datetime import datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from members.models import Member

from .models import CampaignRecipient, CampaignRedemption, MarketingCampaign

logger = logging.getLogger(__name__)

# User story: "As a marketing staff member, I want to create and schedule
# promotional campaigns with a target segment and offer code, so that I can
# launch promotions without needing developer help."
#
# Everything a campaign's offer does once it's saved, with no one switching
# anything on:
#   * audience()      - which members are in its target segment right now;
#   * send_due()      - on the start date, sends the offer to the segment
#                       (in the app + email), and later to anyone who joins the
#                       segment while it runs. Run every minute by the
#                       reminders' background thread (notifications.scheduler);
#   * check_offer()   - whether a code can be used, by this member, for this,
#                       today - with a plain reason when it can't;
#   * redeem()        - records one use (called inside the payment's or sale's
#                       own transaction, so a refused use rolls the charge back).

# Offers go out during the day only: a campaign that starts at midnight is
# sent at 9:00, and nobody is messaged at night.
SEND_FROM = time(9, 0)
SEND_UNTIL = time(21, 0)

DEFAULT_STATUSES = [Member.Status.ACTIVE]
STATUS_WORDS = {
    Member.Status.ACTIVE: "active",
    Member.Status.FROZEN: "frozen or lapsed",
    Member.Status.CANCELLED: "cancelled",
}
USE_WORDS = {
    MarketingCampaign.AppliesTo.MEMBERSHIP: "membership renewals",
    MarketingCampaign.AppliesTo.SHOP: "shop purchases",
    MarketingCampaign.AppliesTo.BOTH: "membership renewals and shop purchases",
}
CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,19}$")


class OfferError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def normalize_code(code):
    return "".join((code or "").split()).upper()


def _day(d):
    return f"{d:%a} {d.day} {d:%b %Y}"


def _join(words, last="or"):
    words = list(words)
    if len(words) <= 1:
        return "".join(words)
    return f"{', '.join(words[:-1])} {last} {words[-1]}"


# --- The target segment ---------------------------------------------------

# The campaign branch's members who match every part of the segment. Works on
# an unsaved campaign too (the audience preview). Erased members are never in
# it. "Active" follows the subscription, not just the stored status: a member
# whose subscription ran out counts as lapsed (Frozen), which is what the
# front desk would show them as.
def audience(campaign, today=None):
    today = today or timezone.localdate()
    members = Member.objects.filter(branch=campaign.branch).exclude(email__endswith=".invalid")

    status_q = Q(pk__in=[])
    for status in campaign.segment_statuses or DEFAULT_STATUSES:
        if status == Member.Status.ACTIVE:
            status_q |= Q(status=Member.Status.ACTIVE, subscription_expires_at__gte=today)
        elif status == Member.Status.FROZEN:
            status_q |= Q(status=Member.Status.FROZEN) | (
                Q(status=Member.Status.ACTIVE)
                & (Q(subscription_expires_at__lt=today) | Q(subscription_expires_at__isnull=True))
            )
        elif status == Member.Status.CANCELLED:
            status_q |= Q(status=Member.Status.CANCELLED)
    members = members.filter(status_q)

    if campaign.segment_plans:
        members = members.filter(membership_plan__in=campaign.segment_plans)
    if campaign.segment_renewal_within_days:
        members = members.filter(
            subscription_expires_at__gte=today,
            subscription_expires_at__lte=today + timedelta(days=campaign.segment_renewal_within_days),
        )
    if campaign.segment_inactive_days:
        from checkins.models import CheckIn

        since = timezone.make_aware(datetime.combine(today - timedelta(days=campaign.segment_inactive_days), time.min))
        recent = CheckIn.objects.filter(result=CheckIn.Result.ALLOWED, checked_in_at__gte=since).values("member_id")
        members = members.exclude(id__in=recent)
    if campaign.segment_joined_within_days:
        members = members.filter(join_date__gte=today - timedelta(days=campaign.segment_joined_within_days))
    return members


def describe_segment(campaign):
    statuses = campaign.segment_statuses or DEFAULT_STATUSES
    who = _join([STATUS_WORDS[s] for s in Member.Status.values if s in statuses])
    text = f"{who[:1].upper()}{who[1:]} members at {campaign.branch}"
    plans = campaign.segment_plans or []
    if plans:
        text += f" on the {_join(plans)} plan{'s' if len(plans) > 1 else ''}"
    parts = []
    if campaign.segment_renewal_within_days:
        n = campaign.segment_renewal_within_days
        parts.append(f"renewing in the next {n} day{'s' if n != 1 else ''}")
    if campaign.segment_inactive_days:
        parts.append(f"not in for {campaign.segment_inactive_days}+ days")
    if campaign.segment_joined_within_days:
        n = campaign.segment_joined_within_days
        parts.append(f"who joined in the last {n} day{'s' if n != 1 else ''}")
    if parts:
        text += ", " + _join(parts, "and")
    return text


# How many members the segment reaches right now, and how: some have turned
# offers off, and some only get them in the app (no email address, or emails
# turned off).
def audience_summary(campaign, today=None):
    from notifications.delivery import wants_email
    from notifications.models import NotificationSettings

    members = list(audience(campaign, today).only("id", "email"))
    ids = [m.id for m in members]
    opted_out = set(NotificationSettings.objects.filter(member_id__in=ids, offers=False).values_list("member_id", flat=True))
    reachable = [m for m in members if m.id not in opted_out]
    return {
        "count": len(members),
        "reachable": len(reachable),
        "byEmail": sum(1 for m in reachable if wants_email(m)),
        "optedOut": len(opted_out),
        "description": describe_segment(campaign),
    }


def in_audience(campaign, member, today=None):
    return (
        campaign.recipients.filter(member=member).exists()
        or audience(campaign, today).filter(pk=member.pk).exists()
    )


# --- Using a code -----------------------------------------------------------

# The campaign a code belongs to today. Two campaigns can share a code only if
# their dates don't overlap, so at most one is running; otherwise the reason
# it can't be used is the nearest one's (starting soon, ended, withdrawn).
def find_offer(code, today=None):
    code = normalize_code(code)
    if not code:
        raise OfferError("Enter an offer code.")
    today = today or timezone.localdate()
    campaigns = list(MarketingCampaign.objects.filter(offer_code=code))
    if not campaigns:
        raise OfferError(f'There\'s no offer with the code "{code}" - check the spelling.')
    for campaign in campaigns:
        if campaign.is_running(today):
            return campaign
    live = [c for c in campaigns if c.is_active]
    upcoming = sorted((c for c in live if c.start_date > today), key=lambda c: c.start_date)
    if upcoming:
        raise OfferError(f"{code} isn't on yet - it starts on {_day(upcoming[0].start_date)}.")
    ended = sorted((c for c in live if c.end_date < today), key=lambda c: c.end_date, reverse=True)
    if ended:
        raise OfferError(f"{code} ended on {_day(ended[0].end_date)}.")
    raise OfferError(f"{code} was withdrawn and can't be used any more.")


def _used_count(campaign):
    return campaign.redemptions.filter(voided_at__isnull=True).count()


def _describe_use(redemption):
    if redemption.use == CampaignRedemption.Use.SHOP:
        return f"shop sale #{redemption.sale_id}" if redemption.sale_id else "a shop purchase"
    if redemption.use == CampaignRedemption.Use.SIGNUP:
        return "a new member sign-up"
    return "a membership renewal"


# Whether `member` can use `code` for `use` (CampaignRedemption.Use) today -
# returns the campaign, or raises OfferError with what to tell them. `branch`
# is where a shop sale is rung up (a code is for its campaign's branch).
def check_offer(code, member, use, *, branch=None, today=None):
    today = today or timezone.localdate()
    campaign = find_offer(code, today)
    code = campaign.offer_code
    if not campaign.covers(use):
        other = {
            CampaignRedemption.Use.SHOP: "shop purchases",
            CampaignRedemption.Use.SIGNUP: "new member sign-ups",
        }.get(use, "membership renewals")
        raise OfferError(f"{code} is for {USE_WORDS[campaign.applies_to]}, not {other}.")
    if branch and branch != campaign.branch:
        raise OfferError(f"{code} is a {campaign.branch} offer - it can't be used at {branch}.")
    if member is None:
        raise OfferError("Add the member to the sale first - an offer code is for particular members.")
    if member.branch != campaign.branch:
        raise OfferError(f"{code} is for {campaign.branch} members, and {member.name} is a {member.branch} member.")
    if use != CampaignRedemption.Use.SIGNUP:
        used = campaign.redemptions.filter(member=member, voided_at__isnull=True).first()
        if used:
            when = timezone.localtime(used.redeemed_at).date()
            raise OfferError(f"{member.name} already used {code} on {_day(when)} ({_describe_use(used)}). It's one use per member.")
        if not in_audience(campaign, member, today):
            raise OfferError(f"{code} isn't for {member.name}. It's for: {describe_segment(campaign).lower()}.")
    if campaign.max_redemptions is not None and _used_count(campaign) >= campaign.max_redemptions:
        raise OfferError(f"{code} has been fully claimed (all {campaign.max_redemptions} uses are gone).")
    return campaign


# check_offer for a sign-up: there's no member yet (the registration form
# is still open), just the branch they're joining at - built into a throwaway
# Member so check_offer's member-shaped checks (branch, audience - skipped
# for a signup) still have something to read.
def check_signup_offer(code, branch, today=None):
    return check_offer(code, Member(branch=branch), CampaignRedemption.Use.SIGNUP, branch=branch, today=today)


# Records one use of the offer. Call it inside the payment's or sale's own
# transaction.atomic(), after creating it: it locks the campaign row so two
# desks can't both take the last use of a capped offer, and the
# one-use-per-member constraint catches the same member at two desks at once.
# Either way it raises OfferError and the caller's transaction rolls back.
def redeem(campaign, member, use, *, amount_before, discount, amount_paid, by=None, payment=None, sale=None):
    locked = MarketingCampaign.objects.select_for_update().get(pk=campaign.pk)
    if not locked.is_running():
        raise OfferError(f"{locked.offer_code} was just withdrawn or has ended - charge again without it.")
    if locked.max_redemptions is not None and _used_count(locked) >= locked.max_redemptions:
        raise OfferError(f"{locked.offer_code} was just fully claimed by someone else - charge again without it.")
    try:
        with transaction.atomic():
            return CampaignRedemption.objects.create(
                campaign=locked, member=member, use=use, payment=payment, sale=sale,
                amount_before=amount_before, discount=discount, amount_paid=amount_paid, redeemed_by=by,
            )
    except IntegrityError:
        raise OfferError(f"{member.name} has just used {locked.offer_code} - it's one use per member.") from None


# A voided sale gives the member their use back.
def release_for_sale(sale):
    return CampaignRedemption.objects.filter(sale=sale, voided_at__isnull=True).update(voided_at=timezone.now())


# --- Sending the offer ------------------------------------------------------

def offer_title(campaign):
    return f"{campaign.name}: {campaign.discount_label} {USE_WORDS[campaign.applies_to]}"[:120]


def offer_text(campaign):
    where = "front desk" if campaign.applies_to == MarketingCampaign.AppliesTo.MEMBERSHIP else "front desk or shop"
    text = (
        f"Use code {campaign.offer_code} at the {campaign.branch} {where} for {campaign.discount_label} "
        f"{USE_WORDS[campaign.applies_to]}, until {_day(campaign.end_date)}. One use per member."
    )
    if campaign.max_redemptions:
        text += f" Limited to the first {campaign.max_redemptions} uses."
    if campaign.offer_message:
        text = f"{campaign.offer_message.strip()} {text}"
    return text[:600]


def _running_offers(today):
    return MarketingCampaign.objects.filter(
        is_active=True, notify_audience=True, start_date__lte=today, end_date__gte=today,
    ).exclude(offer_code="")


# Sends every running campaign's offer to whoever in its segment hasn't had
# it yet - on the first run on (or after) the start date that's the whole
# segment, after that anyone who has joined it since (e.g. a membership that
# now renews within the window). Safe to run as often as you like, and from
# two places at once: each member/campaign pair is recorded once. Returns how
# many offers went out.
def send_due(now=None):
    now = now or timezone.now()
    local = timezone.localtime(now)
    if not (SEND_FROM <= local.time() < SEND_UNTIL):
        return 0
    sent = 0
    for campaign in _running_offers(local.date()):
        try:
            sent += _send(campaign, local.date(), now)
        except Exception:
            logger.exception("Offers: sending campaign %s failed; trying again next time", campaign.pk)
    return sent


def _send(campaign, today, now):
    from notifications.delivery import notify_member, wants_email
    from notifications.models import MemberNotification, NotificationSettings

    if campaign.launched_at is None:
        MarketingCampaign.objects.filter(pk=campaign.pk, launched_at__isnull=True).update(launched_at=now)
    already = campaign.recipients.values("member_id")
    used = campaign.redemptions.filter(voided_at__isnull=True).values("member_id")
    members = list(audience(campaign, today).exclude(id__in=already).exclude(id__in=used))
    opted_out = set(
        NotificationSettings.objects.filter(member__in=members, offers=False).values_list("member_id", flat=True)
    )
    title, text = offer_title(campaign), offer_text(campaign)
    sent = 0
    for member in members:
        # Not recorded, so a member who turns offers back on while it runs still gets it.
        if member.id in opted_out:
            continue
        try:
            with transaction.atomic():
                CampaignRecipient.objects.create(campaign=campaign, member=member, sent_at=now, by_email=wants_email(member))
                notify_member(member, MemberNotification.Kind.OFFER, title, text)
        except IntegrityError:
            continue  # another run got to them first
        sent += 1
    return sent


# Cancelling a campaign whose offer already went out tells everyone who got
# it (and hasn't used it) that the code no longer works - so nobody turns up
# at the desk with it. Returns how many were told.
def notify_withdrawn(campaign):
    from notifications.delivery import notify_member
    from notifications.models import MemberNotification

    used = campaign.redemptions.filter(voided_at__isnull=True).values("member_id")
    told = 0
    for recipient in campaign.recipients.exclude(member_id__in=used).select_related("member"):
        notify_member(
            recipient.member, MemberNotification.Kind.OFFER, f"Offer withdrawn: {campaign.name}"[:120],
            f"Sorry - the {campaign.offer_code} offer ({campaign.discount_label} {USE_WORDS[campaign.applies_to]}) "
            "has been withdrawn and can't be used any more.",
        )
        told += 1
    return told


# --- Reporting ----------------------------------------------------------------

# { campaign id: {"sent", "redeemed", "discountGiven", "revenue"} } for the
# campaign list, in two queries however many campaigns there are.
def results(campaign_ids):
    sent = dict(
        CampaignRecipient.objects.filter(campaign_id__in=campaign_ids)
        .values("campaign_id").annotate(n=Count("id")).values_list("campaign_id", "n")
    )
    # Grouped by use too: a new member's first payment (Signup) is tracked
    # apart from an existing member's redemption (Membership/Shop) - "how
    # many sign-ups vs. how many redemptions did this campaign generate"
    # is the whole point of this story.
    rows = (
        CampaignRedemption.objects.filter(campaign_id__in=campaign_ids, voided_at__isnull=True)
        .values("campaign_id", "use").annotate(n=Count("id"), off=Sum("discount"), paid=Sum("amount_paid"))
    )
    by_campaign = {}
    for row in rows:
        by_campaign.setdefault(row["campaign_id"], {})[row["use"]] = row

    out = {}
    for cid in campaign_ids:
        uses = by_campaign.get(cid, {})
        signup = uses.get(CampaignRedemption.Use.SIGNUP, {})
        others = [v for k, v in uses.items() if k != CampaignRedemption.Use.SIGNUP]
        redeemed_n = sum(v["n"] for v in others)
        redeemed_off = sum((v["off"] or 0) for v in others)
        redeemed_paid = sum((v["paid"] or 0) for v in others)
        signup_paid = signup.get("paid") or 0
        out[cid] = {
            "sent": sent.get(cid, 0),
            "redeemed": redeemed_n,
            "discountGiven": f"{redeemed_off:.2f}",
            "revenue": f"{redeemed_paid:.2f}",
            "signups": signup.get("n", 0),
            "signupDiscountGiven": f"{(signup.get('off') or 0):.2f}",
            "signupRevenue": f"{signup_paid:.2f}",
            "totalRevenue": f"{redeemed_paid + signup_paid:.2f}",
        }
    return out


# The offers a member was sent that they can still use today - shown on their
# home screen so they don't have to dig out the email at the desk.
def offers_for(member, today=None):
    today = today or timezone.localdate()
    used = member.offer_redemptions.filter(voided_at__isnull=True).values("campaign_id")
    rows = (
        CampaignRecipient.objects.filter(
            member=member, campaign__is_active=True, campaign__start_date__lte=today, campaign__end_date__gte=today,
        )
        .exclude(campaign_id__in=used)
        .select_related("campaign")
        .order_by("campaign__end_date", "campaign_id")
    )
    offers = []
    for row in rows:
        c = row.campaign
        claimed = c.max_redemptions is not None and _used_count(c) >= c.max_redemptions
        offers.append({
            "campaignId": c.id,
            "name": c.name,
            "code": c.offer_code,
            "discount": c.discount_label,
            "appliesTo": c.applies_to,
            "for": USE_WORDS[c.applies_to],
            "branch": c.branch,
            "endsOn": c.end_date,
            "message": c.offer_message,
            "fullyClaimed": claimed,
        })
    return offers
