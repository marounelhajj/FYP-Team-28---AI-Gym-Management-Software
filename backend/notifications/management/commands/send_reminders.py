from django.core.management.base import BaseCommand

from notifications.reminders import send_due


# python manage.py send_reminders - sends every class, private session and
# renewal reminder that's due, once. For running from cron or Windows Task
# Scheduler (every few minutes) when REMINDERS_AUTORUN is off; harmless to run
# alongside the background thread too.
class Command(BaseCommand):
    help = "Send the class, private training and membership renewal reminders that are due."

    def handle(self, *args, **options):
        sent = send_due()
        self.stdout.write(f"Sent {sent} reminder{'' if sent == 1 else 's'}.")
