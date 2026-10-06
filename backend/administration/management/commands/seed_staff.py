from django.core.management.base import BaseCommand

from administration.models import Role, StaffAccount

# Demo-only password for every seeded account. Fine for local dev/demo data;
# never used for a real login flow.
DEMO_PASSWORD = "ChangeMe123!"

ROLES = [
    {
        "name": "System Administrator",
        "description": "Full system access: manages staff accounts, roles, and system-wide configuration.",
        "permissions": [
            "manage_members", "manage_staff_accounts", "manage_roles",
            "manage_class_schedule", "manage_billing", "view_financial_reports",
            "manage_marketing_campaigns", "view_audit_log",
        ],
    },
    {
        "name": "General Manager",
        "description": "Cross-branch oversight: organization-wide membership plans, pricing, and reporting.",
        "permissions": ["manage_membership_plans", "manage_branch_promotions", "view_financial_reports"],
    },
    {
        "name": "Branch Manager",
        "description": "Runs day-to-day branch operations: scheduling, budget, local staff, and local promotions.",
        "permissions": ["manage_members", "manage_class_schedule", "manage_branch_promotions", "view_financial_reports"],
    },
    {
        "name": "Receptionist",
        "description": "Front-desk operations: member check-in, registration, and directory lookups.",
        "permissions": ["manage_members"],
    },
    {
        "name": "Marketing Staff",
        "description": "Builds and tracks promotional campaigns and member segments.",
        "permissions": ["manage_marketing_campaigns"],
    },
]

STAFF_ACCOUNTS = [
    {"full_name": "Maya Fakhoury", "email": "maya.fakhoury@gym.com", "username": "mfakhoury", "job_title": "System Administrator", "role": "System Administrator"},
    {"full_name": "Rami Haddad", "email": "rami.haddad@gym.com", "username": "rhaddad", "job_title": "General Manager", "role": "General Manager"},
    {"full_name": "Karim Abboud", "email": "karim.abboud@gym.com", "username": "kabboud", "job_title": "Branch Manager", "role": "Branch Manager"},
    {"full_name": "Dana Sarkis", "email": "dana.sarkis@gym.com", "username": "dsarkis", "job_title": "Receptionist", "role": "Receptionist"},
    {"full_name": "Fadi Ghosn", "email": "fadi.ghosn@gym.com", "username": "fghosn", "job_title": "Receptionist", "role": "Receptionist", "is_active": False},
    {"full_name": "Nadine Khalil", "email": "nadine.khalil@gym.com", "username": "nkhalil", "job_title": "Marketing Staff", "role": "Marketing Staff"},
]


class Command(BaseCommand):
    help = "Seeds default roles and a handful of staff accounts for local development/demo."

    def handle(self, *args, **options):
        if Role.objects.exists() or StaffAccount.objects.exists():
            self.stdout.write(self.style.WARNING(
                "Roles or staff accounts already exist - skipping seed. "
                "Delete them first if you want to reseed."
            ))
            return

        roles_by_name = {}
        for data in ROLES:
            role = Role.objects.create(**data)
            roles_by_name[role.name] = role

        for data in STAFF_ACCOUNTS:
            role_name = data.pop("role")
            is_active = data.pop("is_active", True)
            account = StaffAccount(role=roles_by_name[role_name], is_active=is_active, **data)
            account.set_password(DEMO_PASSWORD)
            account.save()

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(ROLES)} roles and {len(STAFF_ACCOUNTS)} staff accounts "
            f"(demo password for all: {DEMO_PASSWORD})."
        ))
