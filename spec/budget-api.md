---
status: planned
depends_on: [auth.md]
---

# Budget API: categories, allocations, budget view

## Does
Converts the existing server-rendered budget routes (`create_category`, `set_allocation`, `budget_view` in `app.py`) into JWT-protected JSON API endpoints, replacing session/form-based auth with the bearer-token pattern from `auth.md`. Also fixes a pre-existing bug: the old `/categories//allocations` route is missing its `<int:category_id>` path segment (a known heredoc-paste gotcha from this project's original build — see `context/mvp-scope.md`) and cannot actually work as registered.

## Done when
- A logged-in user can create a category, allocate money to it for a given month, and view their budget — all via JSON, all requiring a valid access token.
- Per-user data isolation (IDOR protection) is preserved using the same direct-ownership-check pattern as the original `get_owned_category()`.
- The old server-rendered routes (`/login`, `/logout`, `/categories`, `/categories//allocations`, `/budget`) and their templates are removed — nothing in the new architecture depends on them.

## Integration test contract

### GET /api/budget

**Setup:** An authenticated user with at least one category and an allocation for the current month.
**Action:** `GET /api/budget` (optionally `?month=YYYY-MM-01`), `Authorization: Bearer <access token>`.
**Input:** Optional `month` query param (ISO date, first of month). Defaults to the current month's 1st if omitted.
**Expected output:** `200`, JSON `{"month": "...", "ready_to_assign": "...", "categories": [{"id": ..., "name": "...", "allocated_this_month": "...", "available": "..."}]}`. Same computation as the original `budget_view` (uncategorized inflow minus total allocated = ready to assign; per-category available = total allocated + total spent).
**Side effects:** None (read-only).

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `month` is present but not a valid ISO date, Then** `400`.

### POST /api/categories

**Setup:** An authenticated user.
**Action:** `POST /api/categories`, `Authorization: Bearer <access token>`.
**Input:** JSON `{"name": "..."}`.
**Expected output:** `201`, JSON `{"id": ..., "name": "..."}`.
**Side effects:** A new `Category` row owned by the authenticated user.

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `name` is missing or empty, Then** `400`.
- **When `name` already exists for this user (the `uq_category_user_name` constraint), Then** `409`, no duplicate row created.

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

## Changes
- 001 (2026-08-10) — initial contract, second slice of `changes/001-api-spa-rewrite/plan.md`.
