import base64
import json
import os
import random
import secrets
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from administration import totp
from administration.models import StaffAccount
from audit.models import AuditLog
from billing.models import Payment, PaymentMethod
from checkins.models import CheckIn
from doors.models import Door
from finance.models import Expense
from members.models import Member, Waiver
from members.waiver import WAIVER_VERSION
from retail.models import Product, Sale, SaleItem
from training.models import TrainingEvent

# Realistic, repeatable data for the Sprint 2 demo video (docs/sprint2-demo-script.md).
#
#   GYM_DB_PATH=demo/.data/demo.sqlite3 python manage.py seed_demo --credentials demo/.data/credentials.json
#
# Run by `npm run demo:seed`, which also creates the empty database first.
# It refuses to run unless GYM_DB_PATH points at a separate database file, so
# it can never touch your own dev data. Every login gets a fresh random
# password (and an already-enrolled authenticator secret for staff); they are
# written only to the --credentials file, which is git-ignored.

HAMRA, JNAH = "Hamra", "Jnah"
PRICES = {"Basic": Decimal("25.00"), "Standard": Decimal("40.00"), "Premium": Decimal("50.00")}
FIRST = ["Ali", "Maroun", "Omar", "Layla", "Nour", "Rami", "Dana", "Karim", "Sara", "Hassan", "Mira", "Jad",
         "Yara", "Tarek", "Lina", "Ziad", "Nadine", "Fadi", "Rana", "Elie", "Hiba", "Walid", "Carine", "Bilal"]
LAST = ["Salloum", "El Hajj", "Doughan", "Khoury", "Haddad", "Saad", "Nassar", "Chami", "Aoun", "Sleiman",
        "Fakih", "Mansour", "Rizk", "Daher", "Bou Saab", "Karam"]
# Relative busyness by hour of day (UTC = the app's local time here).
HOUR_WEIGHTS = {6: 5, 7: 9, 8: 8, 9: 5, 10: 3, 11: 3, 12: 5, 13: 5, 14: 3, 15: 3, 16: 5, 17: 9, 18: 12, 19: 11, 20: 7, 21: 3}
# Members the demo script looks up by name.
NAMED = {
    "memberLogin": ("Lea Haddad", HAMRA, "Premium"),
    "deleteLogin": ("Karim Saad", HAMRA, "Standard"),
    "renewal": ("Sami Daher", HAMRA, "Basic"),
    "flag": ("Nour Mansour", HAMRA, "Standard"),
    "card": ("Dana Aoun", HAMRA, "Premium"),
}


def at(day, hour, minute=0):
    return datetime.combine(day, datetime.min.time(), tzinfo=dt_timezone.utc) + timedelta(hours=hour, minutes=minute)


class Command(BaseCommand):
    help = "Seeds a clean, realistic demo database (two main branches) for recording the Sprint 2 demo."

    def add_arguments(self, parser):
        parser.add_argument("--credentials", required=True, help="Where to write the generated demo logins (JSON).")

    def handle(self, *args, **options):
        if not os.environ.get("GYM_DB_PATH"):
            raise CommandError("Set GYM_DB_PATH to a separate database file first (npm run demo:seed does).")
        if Member.objects.exists() or StaffAccount.objects.exists():
            raise CommandError("This database already has data. Start from an empty one (npm run demo:seed).")

        self.rng = random.Random(28)
        self.today = timezone.localdate()
        self.now = timezone.now()
        call_command("seed_staff", verbosity=0)
        call_command("seed_plans", verbosity=0)
        call_command("seed_products", verbosity=0)

        credentials = {"staff": {}, "members": {}, "doors": {}, "named": {}}
        self.staff = self.seed_staff(credentials)
        self.members = self.seed_members(credentials)
        self.seed_payments()
        self.seed_checkins()
        self.seed_sales()
        self.seed_expenses()
        self.seed_audit()
        self.seed_doors(credentials)

        path = Path(options["credentials"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(credentials, indent=2))
        self.stdout.write(self.style.SUCCESS(
            f"Demo data ready: {Member.objects.count()} members, {Payment.objects.count()} payments, "
            f"{CheckIn.objects.count()} check-ins. Logins written to {path}"
        ))

    # --- people -----------------------------------------------------------

    def seed_staff(self, credentials):
        from administration.models import Role

        accounts = {a.username: a for a in StaffAccount.objects.select_related("role")}
        jnah_bm = StaffAccount(
            full_name="Joe Nassar", email="joe.nassar@gym.com", username="jnassar",
            job_title=StaffAccount.JobTitle.BRANCH_MANAGER, role=Role.objects.get(name="Branch Manager"), branch=JNAH,
        )
        jnah_bm.set_password("x")
        jnah_bm.save()
        accounts["jnassar"] = jnah_bm

        for username, account in accounts.items():
            password = secrets.token_urlsafe(12)
            secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
            account.set_password(password)
            account.totp_secret_encrypted = totp.encrypt_secret(secret)
            account.two_factor_enabled = True
            account.save()
            credentials["staff"][username] = {
                "password": password, "totpSecret": secret, "name": account.full_name,
                "role": account.role.name, "branch": account.branch,
            }
        return accounts

    def seed_members(self, credentials):
        rng = self.rng
        specs = [(f"{rng.choice(FIRST)} {rng.choice(LAST)}", branch) for branch, count in
                 [(HAMRA, 26), (JNAH, 20), ("Achrafieh", 5), ("Zalka", 5)] for _ in range(count)]
        named = {key: (name, branch, plan) for key, (name, branch, plan) in NAMED.items()}
        taken = {name for name, _, _ in named.values()}
        members = []
        for key, (name, branch, plan) in named.items():
            members.append(self.make_member(name, branch, plan, key))
        for name, branch in specs:
            if name in taken:
                continue
            taken.add(name)
            plan = rng.choice(["Basic", "Basic", "Standard", "Standard", "Premium"])
            members.append(self.make_member(name, branch, plan))

        for key, login_name in [("memberLogin", "lea.haddad"), ("deleteLogin", "karim.saad")]:
            member = next(m for m in members if m.demo_key == key)
            password = secrets.token_urlsafe(12)
            member.username = login_name
            member.set_password(password)
            member.save(update_fields=["username", "password_hash"])
            credentials["members"][key] = {"username": login_name, "password": password, "name": member.name}
        for member in members:
            if member.demo_key:
                credentials["named"][member.demo_key] = {"name": member.name, "id": member.pk}
        return members

    def make_member(self, name, branch, plan, key=None):
        rng = self.rng
        email = name.lower().replace(" ", ".") + f"{rng.randint(10, 99)}@example.com"
        member = Member.objects.create(
            name=name, email=email, phone=f"+961 7{rng.randint(1000000, 9999999)}", branch=branch,
            membership_plan=plan,
            # The renewal demo member joined long enough ago that two paid months have lapsed.
            join_date=self.today - timedelta(days=100 if key == "renewal" else rng.randint(35, 160)),
            status=Member.Status.ACTIVE,
        )
        member.demo_key = key
        Waiver.objects.create(
            member=member, signature_name=name, health_disclaimer_accepted=True, liability_waiver_accepted=True,
            waiver_version=WAIVER_VERSION, signed_via=Waiver.SignedVia.FRONT_DESK, signed_at=at(member.join_date, 10),
        )
        return member

    # --- money ------------------------------------------------------------

    def seed_payments(self):
        rng = self.rng
        desk = {HAMRA: self.staff["dsarkis"]}
        for member in self.members:
            price = PRICES[member.membership_plan]
            key = member.demo_key
            # Who lapses: a few Frozen (stopped paying), a few Cancelled, the "renewal" demo member expired.
            fate = "active"
            if key == "renewal":
                fate = "frozen"
            elif key is None:
                fate = rng.choices(["active", "frozen", "cancelled"], [78, 12, 10])[0]
            stop_after = rng.randint(1, 3) if fate != "active" else None
            if key == "renewal":
                stop_after = 2

            paid_on = member.join_date
            count = 0
            last = None
            while paid_on <= self.today:
                if stop_after is not None and count >= stop_after:
                    break
                note = "First payment at registration" if count == 0 else "Renewal"
                payment = Payment.objects.create(
                    member=member, amount=price, method=rng.choice(["Cash", "Card", "Card"]), duration="1 Month",
                    expires_at=paid_on + timedelta(days=30), note=note, recorded_by=desk.get(member.branch),
                    method_detail="Card ending 4242" if key == "memberLogin" else "",
                )
                Payment.objects.filter(pk=payment.pk).update(paid_at=at(paid_on, rng.randint(9, 19), rng.randint(0, 59)))
                last = payment
                count += 1
                paid_on += timedelta(days=30)

            member.subscription_expires_at = last.expires_at if last else None
            if fate == "frozen":
                member.status = Member.Status.FROZEN
                member.subscription_expires_at = last.expires_at
            elif fate == "cancelled":
                member.status = Member.Status.CANCELLED
            member.fate = fate
            member.last_paid = last
            member.save(update_fields=["status", "subscription_expires_at"])

            if key in {"memberLogin", "deleteLogin"}:
                PaymentMethod.objects.create(
                    member=member, method="Card", card_holder_name=member.name, card_last4="4242",
                    card_expiry_month=11, card_expiry_year=self.today.year + 2,
                )

    def seed_sales(self):
        rng = self.rng
        products = list(Product.objects.all())
        for _ in range(55):
            branch = rng.choices([HAMRA, JNAH], [60, 40])[0]
            items = []
            total = Decimal("0")
            for product in rng.sample(products, rng.randint(1, 3)):
                qty = rng.randint(1, 2)
                line = product.price * qty
                total += line
                items.append((product, qty, line))
            sale = Sale.objects.create(branch=branch, payment_method=rng.choice(["Cash", "Card"]), total=total,
                                       sold_by=self.staff["dsarkis"] if branch == HAMRA else None)
            day = self.today - timedelta(days=rng.randint(0, 40))
            Sale.objects.filter(pk=sale.pk).update(sold_at=at(day, rng.randint(8, 20), rng.randint(0, 59)))
            SaleItem.objects.bulk_create(
                SaleItem(sale=sale, product=p, product_name=p.name, unit_price=p.price, quantity=q, line_total=line)
                for p, q, line in items
            )

    def seed_expenses(self):
        first_of_month = self.today.replace(day=1)
        last_month = (first_of_month - timedelta(days=1)).replace(day=1)
        plan = {
            HAMRA: [("Rent", 1200, 1), ("Payroll", 3400, 5), ("Utilities", 310, 8), ("Equipment & Maintenance", 260, 12)],
            JNAH: [("Rent", 950, 1), ("Payroll", 2600, 5), ("Utilities", 240, 8)],
        }
        for branch, rows in plan.items():
            for month in (last_month, first_of_month):
                for category, amount, day in rows:
                    incurred = month.replace(day=day)
                    if incurred > self.today:
                        continue
                    Expense.objects.create(branch=branch, category=category, amount=amount, incurred_on=incurred)
        Expense.objects.create(branch=HAMRA, category="Marketing", amount=150, incurred_on=last_month.replace(day=20),
                               note="Instagram campaign")

    # --- activity ---------------------------------------------------------

    def seed_checkins(self):
        rng = self.rng
        by_branch = {}
        for member in self.members:
            if member.fate == "active":
                by_branch.setdefault(member.branch, []).append(member)
        hours, weights = zip(*HOUR_WEIGHTS.items())
        rows = []
        for branch, base in [(HAMRA, 52), (JNAH, 32)]:
            pool = by_branch[branch]
            for back in range(28, -1, -1):
                day = self.today - timedelta(days=back)
                visits = int(base * (0.55 if day.weekday() >= 5 else 1) * rng.uniform(0.8, 1.2))
                for _ in range(visits):
                    hour = rng.choices(hours, weights)[0]
                    start = at(day, hour, rng.randint(0, 59))
                    if start > self.now - timedelta(minutes=5):
                        continue
                    end = start + timedelta(minutes=rng.randint(40, 95))
                    # Still inside right now only if it began in the last 3 hours (stale ones auto-close at 4h).
                    open_now = end > self.now
                    rows.append((branch, rng.choice(pool), start, None if open_now else end))
        # A guaranteed handful inside right now, so the live headcount is never zero.
        for branch, count in [(HAMRA, 7), (JNAH, 4)]:
            for member in rng.sample(by_branch[branch], count):
                rows.append((branch, member, self.now - timedelta(minutes=rng.randint(8, 150)), None))

        checkins = CheckIn.objects.bulk_create(
            CheckIn(member=m, result=CheckIn.Result.ALLOWED, branch=branch) for branch, m, _, _ in rows
        )
        events = []
        for checkin, (branch, member, start, end) in zip(checkins, rows):
            CheckIn.objects.filter(pk=checkin.pk).update(checked_in_at=start, checked_out_at=end)
            events.append(TrainingEvent(
                event_type=TrainingEvent.EventType.CHECK_IN, member=member, branch=branch, occurred_at=start,
                payload={"checkInId": checkin.pk, "method": "qr"},
            ))
        TrainingEvent.objects.bulk_create(events)

    def seed_audit(self):
        rng = self.rng
        entries = []

        def add(action, summary, when, *, actor=None, member=None, branch="", details=None):
            entry = AuditLog(action=action, summary=summary, details=details or {}, created_at=when,
                             ip_address="127.0.0.1", branch=branch or (member.branch if member else ""))
            if isinstance(actor, StaffAccount):
                entry.actor_type = AuditLog.ActorType.STAFF
                entry.actor_staff = actor
                entry.actor_name, entry.actor_username, entry.actor_role = actor.full_name, actor.username, actor.role.name
            elif isinstance(actor, Member):
                entry.actor_type = AuditLog.ActorType.MEMBER
                entry.actor_member = actor
                entry.actor_name, entry.actor_role = actor.name, "Member"
            else:
                entry.actor_type = AuditLog.ActorType.ANONYMOUS
            if member is not None:
                entry.target_type, entry.target_id, entry.target_label = "member", str(member.pk), member.name
            entries.append(entry)

        for member in self.members:
            desk = self.staff["dsarkis"] if member.branch == HAMRA else None
            add(AuditLog.Action.MEMBER_REGISTERED, f"Registered {member.name} on {member.membership_plan}",
                at(member.join_date, 10), actor=desk, member=member)
            if member.fate == "frozen":
                when = at(member.last_paid.expires_at - timedelta(days=rng.randint(0, 6)), rng.randint(9, 20))
                add(AuditLog.Action.MEMBER_FROZEN, f"{member.name} froze their membership in the app",
                    min(when, self.now - timedelta(days=1)), actor=member, member=member)
            elif member.fate == "cancelled":
                when = at(member.last_paid.expires_at - timedelta(days=rng.randint(2, 20)), rng.randint(9, 20))
                add(AuditLog.Action.MEMBER_CANCELLED, f"{member.name} cancelled their membership in the app",
                    min(when, self.now - timedelta(days=1)), actor=member, member=member,
                    details={"previousStatus": "Active"})
                TrainingEvent.objects.create(
                    event_type=TrainingEvent.EventType.CANCELLATION, member=member, branch=member.branch,
                    occurred_at=min(when, self.now - timedelta(days=1)), payload={"channel": "app"},
                )
        for username, account in self.staff.items():
            for back in (0, 1, 2, 4, 7):
                add(AuditLog.Action.STAFF_LOGIN, f"{account.full_name} signed in",
                    self.now - timedelta(days=back, hours=rng.randint(1, 5)), actor=account, branch=account.branch or "")
        add(AuditLog.Action.PLAN_UPDATED, "Edited plan Premium", self.now - timedelta(days=3, hours=2),
            actor=self.staff["rhaddad"], details={"changes": {"price": ["45.00", "50.00"]}})
        AuditLog.objects.bulk_create(entries)

    def seed_doors(self, credentials):
        admin = self.staff["mfakhoury"]
        for branch in (HAMRA, JNAH):
            for kind in (Door.Kind.ENTRANCE, Door.Kind.EXIT):
                door = Door(name=f"{branch} {kind.label}", branch=branch, kind=kind, created_by=admin)
                key = door.set_new_key()
                door.save()
                credentials["doors"][f"{branch} {kind}"] = {"key": key, "branch": branch, "kind": kind}
