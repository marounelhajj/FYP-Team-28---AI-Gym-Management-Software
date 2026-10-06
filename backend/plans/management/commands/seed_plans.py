from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from plans.models import BranchPromotion, MembershipPlan

# Starting tiers reuse the plan names members are already on (Basic /
# Standard / Premium - see members.models.Member.Plan), so seeded demo
# members line up with real plans.
PLANS = [
    {
        "name": "Basic",
        "description": "Gym floor access during standard hours.",
        "price": "35.00",
        "billing_cycle": "Monthly",
        "features": ["Gym floor access", "Locker room"],
    },
    {
        "name": "Standard",
        "description": "Full gym access plus group classes.",
        "price": "55.00",
        "billing_cycle": "Monthly",
        "features": ["Gym floor access", "Locker room", "Unlimited group classes"],
    },
    {
        "name": "Premium",
        "description": "Everything, at every branch, with monthly PT sessions.",
        "price": "90.00",
        "billing_cycle": "Monthly",
        "features": [
            "Gym floor access", "Locker room", "Unlimited group classes",
            "Access to all branches", "2 personal training sessions / month",
        ],
    },
    {
        "name": "Premium Annual",
        "description": "Premium, paid yearly at a discount.",
        "price": "900.00",
        "billing_cycle": "Annual",
        "features": ["Everything in Premium", "2 months free vs. monthly billing"],
    },
]


class Command(BaseCommand):
    help = "Seeds default organization-wide membership plans for local development/demo."

    def handle(self, *args, **options):
        if MembershipPlan.objects.exists():
            self.stdout.write(self.style.WARNING(
                "Membership plans already exist - skipping seed. "
                "Delete them first if you want to reseed."
            ))
            return

        plans_by_name = {data["name"]: MembershipPlan.objects.create(**data) for data in PLANS}

        # A couple of demo local promotions (within each plan's default 20%
        # cap): one running now, one scheduled for next month.
        today = timezone.localdate()
        BranchPromotion.objects.create(
            plan=plans_by_name["Standard"], branch="Hamra", name="Back to Uni",
            discount_type="Percent", discount_value="15.00",
            start_date=today - timedelta(days=3), end_date=today + timedelta(days=25),
        )
        BranchPromotion.objects.create(
            plan=plans_by_name["Premium"], branch="Zalka", name="Zalka Grand Reopening",
            discount_type="Fixed", discount_value="10.00",
            start_date=today + timedelta(days=30), end_date=today + timedelta(days=44),
        )

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(PLANS)} membership plans and 2 branch promotions."))
