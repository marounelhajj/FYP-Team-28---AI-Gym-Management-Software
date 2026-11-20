from decimal import Decimal

from django.core.management.base import BaseCommand

from purchasing.models import ProductSourcing, Supplier
from retail.models import Product

# Demo suppliers for supply orders, and each seeded product's usual supplier,
# cost and reorder level. Safe to run again: existing rows are left as they
# are. The emails use the reserved .example domain, so no purchase order can
# ever reach a real company.

SUPPLIERS = [
    {"name": "NutriPro Lebanon", "contact_name": "Rami Khalil", "email": "orders@nutripro.example", "phone": "01 555 210",
     "supplies": "Supplements, protein, drinks", "lead_time_days": 3},
    {"name": "ActiveWear Co.", "contact_name": "Nadine Sfeir", "email": "sales@activewear.example", "phone": "01 555 340",
     "supplies": "Branded merchandise, towels, gloves", "lead_time_days": 7},
    {"name": "CleanCare Supplies", "contact_name": "Georges Haddad", "email": "orders@cleancare.example", "phone": "01 555 480",
     "supplies": "Cleaning products, paper towels, disinfectant", "lead_time_days": 2},
]

# product name: (supplier, cost to the gym, reorder level)
SOURCING = {
    "Whey Protein 1kg (Chocolate)": ("NutriPro Lebanon", "28.00", 10),
    "Whey Protein 1kg (Vanilla)": ("NutriPro Lebanon", "28.00", 10),
    "Protein Bar": ("NutriPro Lebanon", "1.60", 40),
    "Creatine 300g": ("NutriPro Lebanon", "14.00", 10),
    "Water Bottle 500ml": ("NutriPro Lebanon", "0.35", 60),
    "Sports Drink": ("NutriPro Lebanon", "1.10", 24),
    "Fitness Factory Shaker": ("ActiveWear Co.", "3.50", 10),
    "Fitness Factory T-Shirt": ("ActiveWear Co.", "7.00", 8),
    "Gym Towel": ("ActiveWear Co.", "4.00", 15),
    "Lifting Gloves": ("ActiveWear Co.", "6.50", 6),
}


class Command(BaseCommand):
    help = "Add demo suppliers and the seeded products' usual supplier, cost and reorder level."

    def handle(self, *args, **options):
        suppliers = {}
        for data in SUPPLIERS:
            supplier, created = Supplier.objects.get_or_create(name=data["name"], defaults=data)
            suppliers[supplier.name] = supplier
            self.stdout.write(f"{'Added' if created else 'Kept'} supplier {supplier.name}")
        for name, (supplier_name, cost, level) in SOURCING.items():
            product = Product.objects.filter(name=name).first()
            if product is None:
                continue
            _, created = ProductSourcing.objects.get_or_create(
                product=product,
                defaults={"supplier": suppliers[supplier_name], "unit_cost": Decimal(cost), "reorder_level": level},
            )
            if created:
                self.stdout.write(f"  {name}: {supplier_name}, ${cost}, reorder at {level}")
