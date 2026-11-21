from django.core.management.base import BaseCommand

from marketing.offers import send_due as send_offers
from notifications.reminders import send_due


# python manage.py send_reminders - sends every class, private session and
# renewal reminder that's due, once - and any marketing offers due to go out.
# For running from cron or Windows Task Scheduler (every few minutes) when
# REMINDERS_AUTORUN is off; harmless to run alongside the background thread too.
class Command(BaseCommand):
    help = "Send the class, private training and membership renewal reminders that are due."

    def handle(self, *args, **options):
        sent = send_due()
        offers = send_offers()
        line = f"Sent {sent} reminder{'' if sent == 1 else 's'}."
        if offers:
            line += f" Sent {offers} offer{'' if offers == 1 else 's'}."
        self.stdout.write(line)
