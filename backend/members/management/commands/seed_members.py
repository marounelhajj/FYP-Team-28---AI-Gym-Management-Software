import datetime
from django.core.management.base import BaseCommand
from members.models import Member

FIRST_NAMES = [
    "Ali", "Maroun", "Ahmad", "Omar", "Layla", "Nour", "Rami", "Dana",
    "Karim", "Sara", "Hassan", "Mira", "Jad", "Yara", "Tarek", "Lina",
    "Ziad", "Nadine", "Fadi", "Rana",
]
LAST_NAMES = [
    "Salloum", "El Hajj", "Yateem", "Doughan", "Khoury", "Haddad", "Saad",
    "Nassar", "Chami", "Aoun", "Sleiman", "Fakih", "Mansour", "Rizk",
]
BRANCHES = ["Hamra", "Achrafieh", "Jnah", "Zalka"]
STATUSES = ["Active", "Frozen", "Cancelled"]
PLANS = ["Basic", "Standard", "Premium"]


class Command(BaseCommand):
    help = "Seeds the database with 48 mock members for local development/demo."

    def handle(self, *args, **options):
        if Member.objects.exists():
            self.stdout.write(self.style.WARNING(
                "Members already exist - skipping seed. Delete them first if you want to reseed."
            ))
            return

        members = []
        for i in range(48):
            first = FIRST_NAMES[i % len(FIRST_NAMES)]
            last = LAST_NAMES[(i * 3 + 1) % len(LAST_NAMES)]
            branch = BRANCHES[i % len(BRANCHES)]
            if i % 7 == 0:
                status = "Cancelled"
            elif i % 5 == 0:
                status = "Frozen"
            else:
                status = "Active"
            plan = PLANS[i % len(PLANS)]
            join_date = datetime.date(2024, (i % 12) + 1, (i % 27) + 1)

            members.append(Member(
                name=f"{first} {last}",
                email=f"{first}.{last}".lower().replace(' ', '') + "@email.com",
                phone=f"+961 7{100000 + i * 37}"[:16],
                status=status,
                branch=branch,
                membership_plan=plan,
                join_date=join_date,
            ))

        Member.objects.bulk_create(members)
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(members)} members."))
