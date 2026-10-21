# Running this locally

This folder has two pieces: `backend` (Django + Django REST Framework API)
and `frontend` (React + Vite). Run them in two separate terminals.

## 1. Backend

```bash
cd backend
pip install -r requirements.txt --break-system-packages   # or use a venv if yours works
python manage.py migrate
python manage.py seed_members      # only needed once, skips if data already exists
python manage.py seed_staff        # demo roles + staff logins (password: ChangeMe123!)
python manage.py seed_plans        # demo membership plans (Basic / Standard / Premium)
python manage.py runserver 4000
```

Runs on http://localhost:4000. Try it directly:

```bash
curl "http://localhost:4000/api/members/?q=ali&status=Active"
```

Member data lives in a real SQLite database now (`backend/db.sqlite3`,
git-ignored) managed by Django's ORM — `backend/members/models.py` defines
the `Member` model. `python manage.py seed_members` populates 48 mock
members across our 4 branches for local development/demo, matching the
same shape the old Node mock data used.

## 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Runs on http://localhost:5173 and proxies any `/api/*` request to the
backend on port 4000 (see `frontend/vite.config.js`), so you don't need
to manually configure CORS/URLs — just start both and open
http://localhost:5173.

## What's implemented

Sprint 1 story: *"As a receptionist, I want to search and filter the
member directory by name, membership status, or branch, so that I can
quickly find a member's record."*

- `GET /api/members/` — search by name (`q`), filter by `status` and/or
  `branch`, combinable, paginated (`limit`/`offset`)
- `GET /api/members/meta/` — returns valid status/branch/plan values so the
  frontend dropdowns never hardcode a list that can drift from the data
- `GET /api/members/<id>/` — fetch a single member (for a future member
  detail page)
- `frontend/src/components/MemberDirectory.jsx` — the actual UI: debounced
  search input, status/branch dropdowns, results table with status
  badges, empty/loading/error states, and a "Clear filters" button

The API shape is unchanged from the original Node/Express prototype
(same query params, same JSON response shape, same validation errors),
so the frontend needed zero changes when we swapped backends.

### Membership plans, pricing & branch promotions (SCRUM-49)

Story: *"As a general manager, I want to set organization-wide membership
plans and pricing tiers, so that pricing stays consistent across branches
while still allowing local promotions."*

Lives in its own app, `backend/plans/`.

**Consistent pricing.** Plans have no branch field on purpose: one plan =
one base price at every branch. Each plan also has a
`maxPromoDiscountPercent` (default 20%) set by the general manager. Plans
are archived (`isActive: false`) instead of deleted, since existing members
may still be on them.

**Local promotions.** A `BranchPromotion` is a percent or fixed-amount
discount on one plan, at one branch, between two dates. It is rejected if
it exceeds the plan's cap, and the cap is re-applied whenever a price is
computed, so lowering a cap later shrinks running promotions automatically.
If several promotions overlap, the biggest discount wins.

Plans:
- `GET /api/plans` (`?isActive=true|false`), `POST /api/plans`
- `GET|PATCH /api/plans/<id>` (archive/restore with `{ isActive }`)
- `GET /api/plans/meta` - billing cycles, branches, discount types

Promotions:
- `GET /api/plans/promotions` (`?branch=&planId=`), `POST /api/plans/promotions`
- `GET|PATCH /api/plans/promotions/<id>` (cancel with `{ isActive: false }`)
- `GET /api/plans/pricing?branch=Hamra` - what each active plan costs at
  that branch today (base price, effective price, applied promotion)

Permissions (reads are open; writes return 401 if not logged in, 403 if the
role lacks the permission):
- `manage_membership_plans` - create/edit plans, prices and caps
  (General Manager). Also allows managing promotions.
- `manage_branch_promotions` - create/edit/cancel promotions (Branch
  Manager). Cannot change base prices.

Frontend (`frontend/src/components/plans/`):
- `PlanManager.jsx` / `PlanForm.jsx` - General Manager plan cards and editor
- `PromotionManager.jsx` / `PromotionForm.jsx` - promotions table, branch
  filter, "today's prices at <branch>" strip, and a live preview that warns
  when a discount is over the cap
- `App.jsx` now shows a tab per screen the role allows (GM: Plans +
  Promotions; Branch Manager: Members + Promotions; Receptionist: Members
  only). The System Administrator console is unchanged.

Tests: `python manage.py test plans`

Try it (password `ChangeMe123!`): **rhaddad** (General Manager) and
**kabboud** (Branch Manager). If your local DB was seeded before this
change, `seed_staff` will skip; either delete `db.sqlite3` and reseed, or
log in as the system admin (**mfakhoury**) and add the new permissions to
the roles in Admin Console -> Roles.

### Browse plans & sign up online (SCRUM-66)

Story: *"As a prospective member, I want to browse membership plans and
sign up online, so that I can join a branch without visiting in person
first."*

- `frontend/src/components/member/PlanBrowser.jsx` - public page (no
  login) listing the plans the general manager currently sells, with
  description, features and price. Picking a branch shows that branch's
  price today, including any running branch promotion. Reached from
  "Browse membership plans" on the staff login, or "Browse plans" on the
  member login.
- "Join with <plan>" opens the existing signup form (`MemberSignupPage`)
  with the plan and branch pre-filled, and the form shows the price the
  member will pay. "Compare plans" goes back to the browser.
- Members are no longer limited to the hard-coded Basic/Standard/Premium:
  `Member.membership_plan` now stores the name of any `MembershipPlan`
  (migration `members/0003`). Signup and walk-in registration both reject
  archived or unknown plans, and `GET /api/members/meta` returns the
  active plans, so the receptionist's registration form and the member
  directory offer the real tiers too.
- Requires plans in the database: run `python manage.py seed_plans`, or
  create plans as the general manager.
- Tests: `python manage.py test members`

### Audit log (SCRUM-124)

Story: *"As a system administrator, I want sensitive actions to be written
to an audit log automatically, so that there is a permanent record of who
did what."*

- Lives in its own app, `backend/audit/`. One `AuditLog` row per action:
  when, who (staff account or member, with their name, username and role
  copied onto the row so it still reads right after a rename or
  deactivation), what it was done to, the branch it concerns, a one-line
  summary, `details` (changed fields as `{field: [old, new]}`, a failure
  reason, an amount...) and the IP address.
- **Permanent:** entries can't be edited or deleted. `save()` on an
  existing row, `delete()`, and queryset `update()`/`delete()` all raise
  `AuditLogImmutable`, and the Django admin view is read-only.
- **Written by the server, never the client.** Views call
  `audit.log.record(request, action, actor=..., target=..., summary=...)`
  right after the action succeeds. To log a new kind of action, add it to
  `AuditLog.Action` and call `record()` from your view.
- Logged today: staff sign-ins, failed sign-ins (unknown username, wrong
  password, deactivated account, wrong 2FA code), 2FA lockouts and resets;
  staff accounts created/edited/deactivated/reactivated (password resets
  are flagged, never stored); roles created/edited (permissions
  added/removed); plans and branch promotions created/edited; walk-in
  registrations and online signups; renewals and reactivations; payment
  method changes (masked summary only); access card reissues; member
  profile edits, freezes, resumes and cancellations (staff or the member
  themselves). Reads aren't logged.
- After pulling: `python manage.py migrate` (new `audit` app).
- Tests: `python manage.py test audit`

### Searching the audit log (SCRUM-125)

Story: *"As a general manager, I want to search and filter the audit log by
user, action type, branch and date range, so that I can investigate a
specific incident."*

- **Audit Log** tab for anyone with `view_audit_log`: the General Manager
  (as its own tab) and the System Administrator (inside the Admin Console).
  Migration `audit/0002` adds `view_audit_log` to an existing "General
  Manager" role; `seed_staff` includes it for new databases.
- `GET /api/audit-log` - newest first, paginated (`limit` default 50, max
  200, `offset`). Filters, all combinable:
  - `user` - part of the username or name (also matches the username typed
    in a failed sign-in)
  - `action` - one action (`plan.updated`) or a whole group (`plan`)
  - `branch` - Hamra | Achrafieh | Jnah | Zalka
  - `dateFrom` / `dateTo` - YYYY-MM-DD, both inclusive
- `GET /api/audit-log/meta` - action types (grouped), branches, and the
  users who appear in the log, for the filter dropdowns.
- Click a row to see its details: old and new values, what was affected,
  and the IP address.

### Exporting the audit log (SCRUM-126)

Story: *"As a general manager, I want to export a filtered audit log, so
that I can share evidence in a dispute or review."*

- **Export CSV** button on the Audit Log screen downloads every entry that
  matches the current filters (not just the page on screen).
- `GET /api/audit-log/export` - same filters as `/api/audit-log`, same
  `view_audit_log` permission. Returns `audit-log-<timestamp>.csv`, newest
  first, with a UTF-8 BOM so Excel shows accented names correctly.
- Cells starting with `=`, `+`, `-` or `@` are prefixed with `'` so they
  always open as text, not formulas. Some values are typed by anyone (e.g.
  the username in a failed sign-in).
- Every export is itself logged (`audit_log.exported`: who, which filters,
  how many rows), so there's a record of each copy that left the system.

### AI training data (SCRUM-73)

Story: *"As a system administrator, I want check-ins, cancellations,
no-shows, and trainer accept/reject decisions logged as training data from
first release, so that the models have a dataset to learn from later."*

- Lives in its own app, `backend/training/`. One append-only
  `TrainingEvent` row per event: `event_type` (`check_in`, `cancellation`,
  `no_show`, `trainer_accept`, `trainer_reject`), `occurred_at` (UTC),
  member, branch, optional trainer, optional `session_id` (class session or
  PT booking) and a small JSON `payload`. Indexed on (branch, time) and
  (member, time). Rows can't be edited; they can only be deleted for a
  member's data deletion request.
- **Always on**, no setting to enable. Written today: every allowed
  check-in (branch = the receptionist's branch if they have one, otherwise
  the member's) and every cancellation (front desk and in the app).
  Refused check-in attempts aren't training events.
- **Not wired yet:** `no_show`, `trainer_accept`, `trainer_reject`. There
  are no bookings or coach requests in the app yet; `training/events.py`
  has a TODO showing the call to add when they land.
- **Never breaks the action:** `log_training_event(...)` catches and logs
  any error, so the check-in or cancellation still succeeds.
- **Deletion:** `training.events.delete_training_events_for_member(member_id)`
  removes a member's events (for SCRUM-62, member data deletion). Deleting
  a member also deletes their events.
- `GET /api/training-events` - newest first, paginated (`limit` default
  100, max 500, `offset`). Filters, all combinable: `eventType`, `branch`,
  `memberId`, `dateFrom` / `dateTo` (YYYY-MM-DD, inclusive). Needs
  `view_training_data`, which migration `training/0002` adds to the
  "System Administrator" role.
- After pulling: `python manage.py migrate` (new `training` app).
- Tests: `python manage.py test training`

## Folder structure

```
backend/
  manage.py
  requirements.txt
  gym_backend/           Django project (settings, urls)
  members/
    models.py            Member model (status/branch/plan choices)
    serializers.py        camelCase JSON mapping (membershipPlan, joinDate)
    views.py              GET /api/members/, /meta/, /<id>/
    urls.py
    management/commands/seed_members.py   one-off mock data seeder
  backend-node-reference/   old Node/Express prototype, kept for reference
frontend/
  src/
    api/members.js        fetch wrapper for the members endpoints
    components/
      MemberDirectory.jsx the receptionist-facing search/filter UI
    App.jsx
    main.jsx
```

Everyone adding a new feature: add your own app under `backend/` (e.g.
`python manage.py startapp payments`) or your own route module, and add
your own component under `frontend/src/components/`. Keeping each
feature in its own file/app avoids merge conflicts when we're all
pushing at once.

## Role-based access control (SCRUM-117)

Every staff-only endpoint checks the caller's role server-side via
`administration/permissions.py` (`authorize(request, *permissions)`), so
hiding a screen in the UI is never the only protection. Permissions are read
from the database on each request, so editing a role or deactivating an
account takes effect immediately, even for sessions already open.

| Endpoint | Permission needed |
|---|---|
| `/api/staff`, `/api/staff/<id>`, `POST /api/staff/<id>/2fa/reset` | `manage_staff_accounts` |
| `/api/roles` (read) | `manage_roles` or `manage_staff_accounts` |
| `/api/roles` (create/edit), `/api/permissions` | `manage_roles` |
| `/api/members`, `/api/members/<id>` (read/register) | `manage_members` |
| `POST/PATCH /api/plans` | `manage_membership_plans` |
| `POST/PATCH /api/plans/promotions` | `manage_branch_promotions` or `manage_membership_plans` |
| `GET /api/audit-log`, `/api/audit-log/meta`, `/api/audit-log/export` | `view_audit_log` |
| `GET /api/training-events` | `view_training_data` |

Not logged in -> `401`; logged in without the permission -> `403`. Public:
`/api/plans` reads, `/api/members/meta`, member sign-up/login.

Frontend: tabs shown per role in `App.jsx`, per-tab permission in
`AdminConsole.jsx`, and `components/AccessDenied.jsx` for roles with no pages
or a permission revoked mid-session. A `401` anywhere returns the user to login.

Demo accounts (password `ChangeMe123!`): `mfakhoury` (admin), `rhaddad`
(general manager), `kabboud` (branch manager), `dsarkis` (receptionist),
`nkhalil` (marketing, no pages), `fghosn` (deactivated).

Run tests: `cd backend && python manage.py test`

## Two-factor sign-in for staff (SCRUM-87)

Staff logins take two steps: password (`POST /api/auth/login`), then a
6-digit code from an authenticator app (`POST /api/auth/2fa/verify`). The
staff session is only created after the second step. Members are not
affected.

- **First login** shows a QR code to scan with Google Authenticator,
  Microsoft Authenticator, Authy, etc. Entering the code it shows finishes
  setup, and the next screen lists 10 one-time backup codes (shown once,
  stored only as hashes).
- **Lost phone:** "Use a backup code" on the code screen, or a System
  Administrator clicks **Reset 2FA** in Admin Console -> Staff Accounts; the
  person sets it up again on their next login.
- **Lockout:** 5 wrong codes lock the account for 5 minutes.
- Secrets are encrypted at rest with `TOTP_ENCRYPTION_KEY` (environment
  variable; see `settings.py`). Locally it falls back to a key derived from
  `SECRET_KEY`, so nothing needs setting up for dev.

Logic lives in `administration/totp.py` (codes, encryption, backup codes)
and `administration/auth_views.py` (login, verify, reset). Tests:
`python manage.py test administration`.

Demo tip: each demo account sets up 2FA on its first login, so have an
authenticator app on your phone ready. To start a demo account over, use
Reset 2FA from `mfakhoury`, or reset everyone with
`python manage.py shell -c "from administration.models import StaffAccount; StaffAccount.objects.update(two_factor_enabled=False, totp_secret_encrypted='')"`.
