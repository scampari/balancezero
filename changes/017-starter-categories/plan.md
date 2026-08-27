# Slicing: starter categories for new users

> Date: 2026-08-27
> Status: built
> Branch: changes/017-starter-categories

## What & Why
A new invite-only signup landed on an empty budget page. The user wants
new accounts to start with a usable category structure (Rent/Mortgage,
Utilities, Dining Out, Credit Card Payment, ...) — nothing budgeted, just
something to work off.

## Spec changes
- `spec/signup.md` — `POST /api/signup` side effects gain: a starter
  `Category` tree is created (no `BudgetAllocation` / `CategoryTarget`).
- `context/mvp-scope.md` — note that a starter category *tree* (structure
  only) is distinct from the deferred "budget templates/goals".

## Context changes
- None (no new architectural pattern — just `Category` rows).

## Constraints
- **Fixed list in `starter_categories.py`**: 8 groups
  (Housing / Food / Transportation / Debt Payments / Health / Personal /
  Entertainment / Savings) each with 2–3 subcategories, plus a flat
  "Miscellaneous". ~29 rows. Names unique (the `(user_id, name)`
  constraint); one level of nesting; `position` gap-free per sibling
  group.
- **`create_starter_categories(user_id)`** — inserts the tree, **no-op if
  the user already has any category**. Caller commits. Zero allocations,
  zero targets → `ready_to_assign` unaffected, and each group is an
  `is_group` total of its children (changes/014) at $0.
- Wired into `auth_api.signup` (after the user flush) and
  `seed_real_user.py` (guarded, so a password-reset re-run doesn't
  duplicate). The demo user is unaffected — `seed_demo.py` has its own
  data.

## Non-Goals
- An operator-editable template / per-invite templates / a "choose your
  starter set" step — the list is a code constant.
- Seeding allocations, targets, or accounts.
- Backfilling existing users.

## Slices
- **017-A** backend — `starter_categories.py`; call from
  `auth_api.signup` + `seed_real_user.py`. `tests/test_signup.py` +2
  (tree shape + `parent_id`s + no allocations; `ready_to_assign` stays
  "0" and "Housing" is an `is_group`).
- **017-B** — e2e `signup.spec.ts` asserts "Housing" / "Groceries" rows
  are visible on the budget page right after signup. No other frontend
  change (the budget page already renders whatever categories exist).

## Verification
- `venv/bin/pytest` — 212 passed / 6 skipped (was 210/6).
- `cd frontend && npm run build && npm run lint` clean (2 pre-existing
  warnings).
- `npm run test:e2e` — 25 passed.
