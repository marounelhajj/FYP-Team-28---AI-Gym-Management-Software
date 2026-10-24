from django.core.management.base import BaseCommand

from members.models import Member
from retail.models import BranchStock, Product

# Demo shop shelf for local development: a few products in each category,
# with some stock at every branch (and one item sold out at Zalka, so the
# till's "out of stock" state is easy to see).
PRODUCTS = [
    ("Whey Protein 1kg (Chocolate)", "Supplements", "45.00", 12),
    ("Whey Protein 1kg (Vanilla)", "Supplements", "45.00", 8),
    ("Protein Bar", "Supplements", "3.50", 60),
    ("Creatine 300g", "Supplements", "25.00", 10),
    ("Water Bottle 500ml", "Drinks", "1.00", 120),
    ("Sports Drink", "Drinks", "2.50", 48),
    ("Fitness Factory Shaker", "Merchandise", "8.00", 25),
    ("Fitness Factory T-Shirt", "Merchandise", "18.00", 20),
    ("Gym Towel", "Merchandise", "10.00", 15),
    ("Lifting Gloves", "Merchandise", "15.00", 10),
]


class Command(BaseCommand):
    help = "Seeds a demo retail catalog with stock at every branch."

    def handle(self, *args, **options):
        if Product.objects.exists():
            self.stdout.write(self.style.WARNING("Retail products already exist - skipping seed."))
            return

        for name, category, price, quantity in PRODUCTS:
            product = Product.objects.create(name=name, category=category, price=price)
            BranchStock.objects.bulk_create(
                BranchStock(
                    product=product, branch=branch,
                    quantity=0 if (branch == "Zalka" and category == "Drinks" and price == "2.50") else quantity,
                )
                for branch in Member.Branch.values
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(PRODUCTS)} retail products."))
