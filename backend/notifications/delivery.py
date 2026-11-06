import logging

from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import MemberNotification, NotificationSettings

logger = logging.getLogger(__name__)

# The one way a member gets told something: an in-app notification (the bell
# in their top bar, which also pops a desktop alert if they allowed it in the
# browser) plus the same message by email, unless they turned email off.
#
# Email goes through Django's own email sending (settings.EMAIL_BACKEND), so
# any mail provider works - Gmail, SendGrid, Mailgun, a university server -
# by setting EMAIL_HOST and friends in the environment, with no code change.
# In development it's written to backend/sent_emails/ instead of being sent.
#
# The email only goes once the database change it describes is saved
# (transaction.on_commit), so nobody is told about a booking that was rolled
# back - and a mail server that's down never breaks the booking itself.

SIGN_OFF = (
    "\n\nSee the details in the Fitness Factory app. To change which reminders you get, or stop these emails, "
    "open Reminders in the app.\n\nFitness Factory"
)


def notify_member(member, kind, title, message):
    notification = MemberNotification.objects.create(
        recipient=member, kind=kind, title=title[:120], message=message[:600],
    )
    if wants_email(member):
        transaction.on_commit(lambda: _email(notification.pk))
    return notification


# An erased member's address ends in .invalid; no settings row means the default (yes).
def wants_email(member):
    if not member.email or member.email.endswith(".invalid"):
        return False
    choice = NotificationSettings.objects.filter(member=member).values_list("email", flat=True).first()
    return choice is not False


def _email(notification_id):
    notification = MemberNotification.objects.select_related("recipient").filter(pk=notification_id).first()
    if notification is None:
        return
    member = notification.recipient
    first_name = member.name.split(" ")[0]
    try:
        send_mail(
            subject=notification.title,
            message=f"Hi {first_name},\n\n{notification.message}{SIGN_OFF}",
            from_email=None,  # settings.DEFAULT_FROM_EMAIL
            recipient_list=[member.email],
        )
    except Exception:
        logger.exception("Couldn't email notification %s to member %s", notification_id, member.pk)
        return
    MemberNotification.objects.filter(pk=notification_id).update(emailed_at=timezone.now())
