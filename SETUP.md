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
python manage.py seed_plans        # demo membership plans (Basic / Standard / Premium / Premium Annual)
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
