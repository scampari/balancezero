---
status: in-progress
depends_on: [auth.md]
---

# Budget API: categories, allocations, budget view

## Does
Converts the existing server-rendered budget routes (`create_category`, `set_allocation`, `budget_view` in `app.py`) into JWT-protected JSON API endpoints, replacing session/form-based auth with the bearer-token pattern from `auth.md`. Also fixes a pre-existing bug: the old `/categories//allocations` route is missing its `<int:category_id>` path segment (a known heredoc-paste gotcha from this project's original build — see `context/mvp-scope.md`) and cannot actually work as registered.

## Done when
- A logged-in user can create a category, allocate money to it for a given month, and view their budget — all via JSON, all requiring a valid access token.
- Per-user data isolation (IDOR protection) is preserved using the same direct-ownership-check pattern as the original `get_owned_category()`.
- The old server-rendered routes (`/login`, `/logout`, `/categories`, `/categories//allocations`, `/budget`) and their templates are removed — nothing in the new architecture depends on them.
- A user can set a budget target on any category — monthly, yearly, or by a custom date — and see it, plus a computed monthly contribution amount, in the budget view. Setting a new target supersedes the previous one rather than deleting it (`changes/005-budget-targets-and-tbb/plan.md`).
- `ready_to_assign` reflects transactions the user has explicitly marked `is_income` (see `spec/transactions.md`), not an implicit "uncategorized = income" assumption.

## Integration test contract

### GET /api/budget

**Setup:** An authenticated user with at least one category and an allocation for the current month.
**Action:** `GET /api/budget` (optionally `?month=YYYY-MM-01`), `Authorization: Bearer <access token>`.
**Input:** Optional `month` query param (ISO date, first of month). Defaults to the current month's 1st if omitted.
**Expected output:** `200`, JSON `{"month": "...", "ready_to_assign": "...", "categories": [{"id": ..., "name": "...", "parent_id": ... | null, "allocated_this_month": "...", "available": "...", "target": null | {"target_type": "monthly"|"yearly"|"custom", "target_amount": "...", "target_date": "..." | null, "monthly_target_amount": "..."}}]}`. `available`/`allocated_this_month`/`target` are computed identically regardless of hierarchy — a subcategory's numbers work exactly like any other category's. `target` is `null` when the category has no active target (`superseded_at IS NULL` row in `CategoryTarget`); `monthly_target_amount` is `target_amount` as-is for `monthly`, else `target_amount ÷ months remaining` (current month through `target_date` inclusive for `custom`, through December of the current year for `yearly`).
**Side effects:** None (read-only).

`ready_to_assign` **(changed this slice):** was "uncategorized inflow minus total allocated"; now `SUM(Transaction.amount WHERE is_income = true, joined through the user's accounts) − SUM(BudgetAllocation.allocated_amount)` (both cumulative across all months, matching the original's cumulative — not month-scoped — semantics). `is_income` and `category_id` are mutually exclusive (`spec/transactions.md`), so this is equivalent to the old uncategorized-inflow query restricted to the new explicit flag. No per-transaction backfill of existing data — a one-time per-account "Starting Balance" `is_income` transaction (see `spec/transactions.md`'s Notes) reconciles current bank balances into this sum instead, so `ready_to_assign` is not silently `0` on day one.

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `month` is present but not a valid ISO date, Then** `400`.

### POST /api/categories/<int:category_id>/target

**Setup:** An authenticated user owns the target category.
**Action:** `POST /api/categories/<category_id>/target`, `Authorization: Bearer <access token>`.
**Input:** JSON `{"target_type": "monthly"|"yearly"|"custom", "target_amount": "123.45", "target_date": "YYYY-MM-DD"}` — `target_date` required when `target_type` is `custom`, forbidden otherwise.
**Expected output:** `201`, JSON `{"id": ..., "category_id": ..., "target_type": "...", "target_amount": "...", "target_date": "..." | null, "monthly_target_amount": "..."}`.
**Side effects:** A new `CategoryTarget` row created. If the category already had an active target (`superseded_at IS NULL`), that row's `superseded_at` is set to now — superseded, never deleted (same pattern this project uses for specs, see `spec/README.md`).

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `category_id` doesn't exist at all, Then** `404`.
- **When `category_id` exists but is owned by a different user, Then** `403`.
- **When `target_type` is missing or not one of `monthly`/`yearly`/`custom`, Then** `400`.
- **When `target_amount` is missing or not a valid decimal, Then** `400`.
- **When `target_amount` is zero or negative, Then** `400` — a target is a goal to work toward, zero/negative isn't meaningful (same reasoning as allocations must be zero-or-positive, but here strictly positive since a zero target is a no-op).
- **When `target_type` is `custom` and `target_date` is missing, Then** `400`.
- **When `target_type` is `custom` and `target_date` isn't a valid ISO date, Then** `400`.
- **When `target_type` is `custom` and `target_date` is not after the current month (today or earlier), Then** `400` — a target date in the past/current month leaves zero or negative months remaining, undefined for the `monthly_target_amount` computation.
- **When `target_type` is `monthly` or `yearly` and `target_date` is present, Then** `400` — `target_date` only applies to `custom`.

### GET /api/categories/<int:category_id>/target

**Setup:** An authenticated user owns the target category, which may or may not have an active target.
**Action:** `GET /api/categories/<category_id>/target`, `Authorization: Bearer <access token>`.
**Input:** None beyond the path segment.
**Expected output:** `200`, JSON `{"target": null}` if no active target exists, else `{"target": {"id": ..., "category_id": ..., "target_type": "...", "target_amount": "...", "target_date": "..." | null, "monthly_target_amount": "..."}}`.
**Side effects:** None (read-only).

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `category_id` doesn't exist at all, Then** `404`.
- **When `category_id` exists but is owned by a different user, Then** `403`.

### POST /api/categories

**Setup:** An authenticated user.
**Action:** `POST /api/categories`, `Authorization: Bearer <access token>`.
**Input:** JSON `{"name": "...", "parent_id": <int>}` — `parent_id` optional.
**Expected output:** `201`, JSON `{"id": ..., "name": "...", "parent_id": ... | null}`.
**Side effects:** A new `Category` row owned by the authenticated user.
A category with a `parent_id` is a subcategory — purely organizational,
still independently allocatable and assignable to transactions exactly
like a top-level category (see `context/mvp-scope.md` / Notes below —
no budget-math change based on hierarchy).

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `name` is missing or empty, Then** `400`.
- **When `name` already exists for this user (the `uq_category_user_name` constraint), Then** `409`, no duplicate row created.
- **When `parent_id` doesn't exist at all, Then** `404`.
- **When `parent_id` exists but is owned by a different user, Then** `403`.
- **When `parent_id` refers to a category that itself already has a `parent_id`, Then** `400` — two levels only, a subcategory cannot itself have subcategories.

### POST /api/categories/<int:category_id>/allocations

**Setup:** An authenticated user owns the target category.
**Action:** `POST /api/categories/<category_id>/allocations`, `Authorization: Bearer <access token>`.
**Input:** JSON `{"month": "YYYY-MM-01", "amount": "123.45"}`.
**Expected output:** `200`, JSON `{"category_id": ..., "month": "...", "allocated_amount": "..."}`. Upserts — creates the allocation if none exists for that category+month, updates it if one does (matches original `set_allocation` behavior).
**Side effects:** A `BudgetAllocation` row created or updated.

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `category_id` doesn't exist at all, Then** `404`.
- **When `category_id` exists but is owned by a different user, Then** `403` (never `404` — that would leak existence to an unauthorized caller in a way inconsistent with the rest of the app, matching the original `get_owned_category` behavior exactly).
- **When `month` or `amount` is missing, Then** `400`.
- **When `amount` isn't a valid decimal, Then** `400`.
- **When `amount` is negative, Then** `400` — allocations must be zero or positive (decided 2026-08-10: a negative allocation isn't a meaningful action in zero-based budgeting; overspending shows up as a negative *available* balance, not a negative allocation).
- **When `month` isn't a valid ISO date, Then** `400`.

## Notes
- Reuses `get_owned_category`'s ownership-check pattern (404 for nonexistent, 403 for wrong-owner) — see `context/security-requirements.md`.
- The pre-existing `/categories//allocations` route bug (missing `<int:category_id>` placeholder) is fixed by this slice's correctly-declared `/api/categories/<int:category_id>/allocations` route — not a separate fix, just don't repeat the mistake.
- Removing the old templates (`login.html`, `budget.html`) and the `login_required` decorator / session-based `get_owned_category` helper happens in this slice too, once the new routes are green — no reason to keep dead code around once nothing references it.
- **Target storage (005):** new `CategoryTarget` table — `category_id` FK, `target_type` (`monthly`/`yearly`/`custom`), `target_amount`, `target_date` nullable, `created_at`, `superseded_at` nullable. "Active" = `superseded_at IS NULL`; at most one active row per category, enforced at the application layer (the POST handler supersedes the prior active row in the same transaction it inserts the new one), not a DB constraint — mirrors how `BudgetAllocation`'s upsert is handled in code rather than via a partial unique index.
- **`monthly_target_amount` months-remaining math (005):** for `custom`, months remaining = whole calendar months from the current month up to and including `target_date`'s month (e.g. planned in March for a June target = 4: Mar, Apr, May, Jun). For `yearly`, months remaining = months from the current month through December of the current year, inclusive. Division is `target_amount / months_remaining` using `Decimal`, no special rounding rule specified — round to cents (2 decimal places) same as every other money field in this app.
- **`is_income` computation (005):** filters on `Transaction.is_income = true` joined through `Account.user_id`, no separate `category_id IS NULL` filter needed — mutual exclusivity is enforced at write time in `spec/transactions.md`'s `PATCH` contract, so the two conditions can never diverge for a valid row.

## Tests
- `tests/test_budget_api.py` § `"test_create_category_with_valid_name_returns_201"` — covers § POST /api/categories contract.
- `tests/test_budget_api.py` § `"test_create_category_without_token_returns_401"` — covers § POST /api/categories error case: no token.
- `tests/test_budget_api.py` § `"test_create_category_with_empty_name_returns_400"` — covers § POST /api/categories error case: empty name.
- `tests/test_budget_api.py` § `"test_create_category_with_missing_name_returns_400"` — covers § POST /api/categories error case: missing name.
- `tests/test_budget_api.py` § `"test_create_category_with_duplicate_name_returns_409"` — covers § POST /api/categories error case: duplicate name.
- `tests/test_budget_api.py` § `"test_set_allocation_creates_new_allocation_returns_200"` — covers § POST allocations contract (create).
- `tests/test_budget_api.py` § `"test_set_allocation_on_existing_month_updates_it_not_duplicates"` — covers § POST allocations contract (upsert).
- `tests/test_budget_api.py` § `"test_set_allocation_without_token_returns_401"` — covers § POST allocations error case: no token.
- `tests/test_budget_api.py` § `"test_set_allocation_on_nonexistent_category_returns_404"` — covers § POST allocations error case: category not found. Note: this test passes even before the route exists, since Flask's own routing 404 coincides with the domain 404 — not a real green until the route is actually implemented; re-verified manually during build.
- `tests/test_budget_api.py` § `"test_set_allocation_on_another_users_category_returns_403"` — covers § POST allocations error case: wrong owner.
- `tests/test_budget_api.py` § `"test_set_allocation_missing_month_returns_400"` / `"test_set_allocation_missing_amount_returns_400"` — covers § POST allocations error cases: missing fields.
- `tests/test_budget_api.py` § `"test_set_allocation_invalid_amount_format_returns_400"` — covers § POST allocations error case: invalid decimal.
- `tests/test_budget_api.py` § `"test_set_allocation_negative_amount_returns_400"` — covers § POST allocations error case: negative amount.
- `tests/test_budget_api.py` § `"test_set_allocation_invalid_month_format_returns_400"` — covers § POST allocations error case: invalid month.
- `tests/test_budget_api.py` § `"test_get_budget_returns_ready_to_assign_and_categories"` — covers § GET /api/budget contract.
- `tests/test_budget_api.py` § `"test_get_budget_without_month_param_defaults_to_current_month"` — covers § GET /api/budget default-month behavior.
- `tests/test_budget_api.py` § `"test_get_budget_without_token_returns_401"` — covers § GET /api/budget error case: no token.
- `tests/test_budget_api.py` § `"test_get_budget_invalid_month_format_returns_400"` — covers § GET /api/budget error case: invalid month.
- `tests/test_budget_api.py` § `"test_get_budget_only_shows_authenticated_users_categories"` — covers § per-user isolation (not a separately listed error case, but implied by the IDOR/isolation requirement in context/security-requirements.md).

18 of 19 tests fail with 404 (no routes registered yet) — confirmed red before commit. The 19th is documented above.

- `tests/test_budget_api.py` § `"test_set_monthly_target_returns_201"` — covers § POST target contract (monthly).
- `tests/test_budget_api.py` § `"test_set_yearly_target_computes_monthly_target_amount"` — covers § POST target contract (yearly, `monthly_target_amount` computation).
- `tests/test_budget_api.py` § `"test_set_custom_target_computes_monthly_target_amount"` — covers § POST target contract (custom, `monthly_target_amount` computation).
- `tests/test_budget_api.py` § `"test_set_target_supersedes_previous_target_not_deletes"` — covers § POST target side effect (supersede, not delete).
- `tests/test_budget_api.py` § `"test_set_target_without_token_returns_401"` — covers § POST target error case: no token.
- `tests/test_budget_api.py` § `"test_set_target_on_nonexistent_category_returns_404"` — covers § POST target error case: category not found. Passes even pre-implementation (Flask routing 404 coincides); not a real green until built, same caveat as the allocations contract above.
- `tests/test_budget_api.py` § `"test_set_target_on_another_users_category_returns_403"` — covers § POST target error case: wrong owner.
- `tests/test_budget_api.py` § `"test_set_target_missing_target_type_returns_400"` / `"test_set_target_invalid_target_type_returns_400"` — covers § POST target error case: invalid `target_type`.
- `tests/test_budget_api.py` § `"test_set_target_missing_target_amount_returns_400"` / `"test_set_target_invalid_target_amount_format_returns_400"` — covers § POST target error case: invalid `target_amount`.
- `tests/test_budget_api.py` § `"test_set_target_zero_amount_returns_400"` / `"test_set_target_negative_amount_returns_400"` — covers § POST target error case: non-positive amount.
- `tests/test_budget_api.py` § `"test_set_target_custom_missing_target_date_returns_400"` — covers § POST target error case: custom without date.
- `tests/test_budget_api.py` § `"test_set_target_custom_invalid_target_date_format_returns_400"` — covers § POST target error case: invalid date format.
- `tests/test_budget_api.py` § `"test_set_target_custom_target_date_not_in_future_returns_400"` — covers § POST target error case: date not after current month.
- `tests/test_budget_api.py` § `"test_set_target_monthly_with_target_date_returns_400"` — covers § POST target error case: `target_date` forbidden outside `custom`.
- `tests/test_budget_api.py` § `"test_get_target_returns_active_target"` / `"test_get_target_returns_null_when_none_set"` — covers § GET target contract.
- `tests/test_budget_api.py` § `"test_get_target_without_token_returns_401"` — covers § GET target error case: no token.
- `tests/test_budget_api.py` § `"test_get_target_on_nonexistent_category_returns_404"` — covers § GET target error case: category not found. Same pre-implementation-pass caveat as above.
- `tests/test_budget_api.py` § `"test_get_target_on_another_users_category_returns_403"` — covers § GET target error case: wrong owner.

20 of 22 new tests confirmed red (404, no route) before commit; the 2 nonexistent-category tests pass pre-implementation for the same reason documented above.

No test exists yet for the `ready_to_assign`/`is_income` change to § GET /api/budget, or for `spec/transactions.md`'s `is_income` toggle — second slice, test-writer will produce these when that slice is built.

## Changes
- 001 (2026-08-10) — initial contract, second slice of `changes/001-api-spa-rewrite/plan.md`.
- 001 (2026-08-10) — built. New `budget_api.py` blueprint; old server-rendered routes, templates, and flask_wtf removed. All 19 tests green (36 total with auth.md's suite, no regressions).
- 005 (2026-08-26) — added § POST/GET /api/categories/<id>/target (category budget targets: monthly/yearly/custom, superseded-not-deleted history) and changed `ready_to_assign` to read `Transaction.is_income` instead of implicit uncategorized-inflow. Second half of `changes/005-budget-targets-and-tbb/plan.md`, paired with `spec/transactions.md`'s `is_income` toggle. Not yet built.
- 005 (2026-08-26) — § POST/GET /api/categories/<id>/target built. New `CategoryTarget` model + migration (`e6875d83ae67`); `budget_api.py` gains `set_target`/`get_target`. All 22 target tests green, 92/92 full suite (9 skipped — Plaid sandbox tests requiring real credentials). `ready_to_assign`/`is_income` half of this slice (second half, paired with `spec/transactions.md`) not yet built — status stays `in-progress`.
