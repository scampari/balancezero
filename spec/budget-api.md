---
status: built
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
**Expected output:** `200`, JSON:
```
{"month": "...", "ready_to_assign": "...",
 "totals": {"budgeted": "...", "spent": "...", "available": "...", "rollover": "..."},
 "categories": [ <entry>, ... ],
 "archived_categories": [ <entry>, ... ]}
```
where each `<entry>` is `{"id": ..., "name": "...", "parent_id": ... | null, "position": <int>, "archived": <bool>, "is_group": <bool>, "allocated_this_month": "...", "spent_this_month": "...", "available": "...", "rollover": "...", "target": null | {"target_type": "monthly"|"yearly"|"custom", "target_amount": "...", "target_date": "..." | null, "monthly_target_amount": "...", "months_remaining": <int>, "funded": "...", "needed_this_month": "...", "progress": "..."}}`.

- `categories` holds only non-archived categories, ordered by `(position, id)`; `archived_categories` holds only archived ones, ordered by name. `archived` is `true` on every entry in the second list, `false` in the first.
- **Category groups (changes/014 — reverses the earlier "no roll-up"):** a top-level category with at least one non-archived child is a **group**. Its entry has `"is_group": true` and its `allocated_this_month` / `spent_this_month` / `available` are the **sum of its non-archived children's** values plus any of the parent's own legacy amounts (so money budgeted before the split doesn't vanish). `target` is `null` for a group. A group cannot be allocated to (`POST /api/categories/<id>/allocations` → `400`) or have transactions assigned to it (`PATCH` / `POST /api/transactions` → `400`). A leaf category (has a parent, or a top-level with no children) is unchanged: `"is_group": false`, its own numbers, editable. `totals` still sums each category's *own* values, so a group and its children are never double-counted.
- `allocated_this_month` = the category's `BudgetAllocation.allocated_amount` for the requested `month` (or `"0"`). `spent_this_month` = signed `SUM(Transaction.amount)` for the category within the requested month (outflows negative).
- **`available` and `rollover` are month-bounded (changes/025 — supersedes the 006 "cumulative, not month-scoped" rule).** For the viewed month `M` (with `end` = first day of `M+1`): `available` = `SUM(allocations WHERE month <= M) + SUM(signed transactions WHERE posted_at < end)` — the envelope balance as of the end of `M`. Activity dated in any later month is not visible. `rollover` = `available − allocated_this_month − spent_this_month` = what carried in from months before `M` (negative if the category was overspent through the end of the prior month, positive for a leftover balance). Overspending therefore rolls forward inside the category; it never touches `ready_to_assign`.
- `totals` = the sum of `allocated_this_month` / `spent_this_month` / `available` / `rollover` over `categories` only (archived excluded).
- `target` is `null` when the category has no active target (`superseded_at IS NULL` row in `CategoryTarget`). `monthly_target_amount` is unchanged from the 005 contract — `target_amount` as-is for `monthly`, else `target_amount ÷ months remaining` — a progress-blind baseline. The 006 progress fields: `months_remaining` is `1` for `monthly`, else whole calendar months from the current month through the horizon inclusive (`target_date`'s month for `custom`, December for `yearly`). `funded` is what's already set aside — `allocated_this_month` for `monthly`, else `max(0, available)`. `needed_this_month` is what to assign now to stay on pace — `max(0, target_amount − funded)` for `monthly`, else `max(0, (target_amount − funded) ÷ months_remaining)`, rounded to cents. `progress` is `min(1, funded ÷ target_amount)` (4 dp).
**Side effects:** None (read-only).

`ready_to_assign` **(005; month-scoped by changes/025):** `SUM(Transaction.amount WHERE is_income = true, joined through the user's accounts, posted_at < end) − SUM(BudgetAllocation.allocated_amount WHERE month <= M)` for the viewed month `M` (`end` = first day of `M+1`). Income received in a later month, and money assigned to a later month, do not affect an earlier month's figure — they land once that month (or a later one) is the one being viewed. Was, pre-005: "uncategorized inflow minus total allocated"; 005 switched the income side to the explicit `is_income` flag; 025 added the month bounds (previously both sides were cumulative across all months). `is_income` and `category_id` are mutually exclusive (`spec/transactions.md`), so this is equivalent to the old uncategorized-inflow query restricted to the new explicit flag. No per-transaction backfill of existing data — a one-time per-account "Starting Balance" `is_income` transaction (see `spec/transactions.md`'s Notes) reconciles current bank balances into this sum instead, so `ready_to_assign` is not silently `0` on day one.

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
A category with a `parent_id` is a subcategory. Adding the first child to a
top-level category turns that parent into a **group** (see the `GET
/api/budget` contract's `is_group` bullet): the group is no longer directly
allocatable or transaction-assignable — its columns total its children.

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `name` is missing or empty, Then** `400`.
- **When `name` already exists for this user (the `uq_category_user_name` constraint), Then** `409`, no duplicate row created.
- **When `parent_id` doesn't exist at all, Then** `404`.
- **When `parent_id` exists but is owned by a different user, Then** `403`.
- **When `parent_id` refers to a category that itself already has a `parent_id`, Then** `400` — two levels only, a subcategory cannot itself have subcategories.

### PATCH /api/categories/<int:category_id>

**Setup:** An authenticated user owns the target category.
**Action:** `PATCH /api/categories/<category_id>`, `Authorization: Bearer <access token>`.
**Input:** JSON with any subset of `{"name": "...", "parent_id": <int> | null, "archived": <bool>, "position": <int>}`.
**Expected output:** `200`, JSON `{"id": ..., "name": "...", "parent_id": ... | null, "archived": <bool>, "position": <int>}` reflecting the new state.
**Side effects:**
- `name` — renamed in place.
- `parent_id` — reparented; `null` promotes to top level. On reparent the category lands at the end of the destination sibling group and both the old and new groups' `position` values are re-packed gap-free to `0..n-1`.
- `archived` — soft-hides (`true`) or restores (`false`) the category. Archived categories keep every transaction and allocation row they own; they move to `archived_categories` in `GET /api/budget` and drop out of `totals`.
- `position` — moves the category to that index within its sibling group `(user_id, parent_id)`, clamped to the group's bounds; the whole group is then re-packed to `0..n-1`. Applied after any reparent in the same request.

No delete endpoint exists — categories are archived, never removed, so their historical transaction/allocation associations stay intact.

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `category_id` doesn't exist at all, Then** `404`.
- **When `category_id` exists but is owned by a different user, Then** `403`.
- **When the body carries none of `name`/`parent_id`/`archived`/`position`, Then** `400`.
- **When `name` is present but empty/whitespace, Then** `400`.
- **When `name` collides with another of the user's categories (`uq_category_user_name`), Then** `409`.
- **When `parent_id` equals the category's own id, Then** `400`.
- **When `parent_id` refers to a nonexistent category, Then** `400` (a bad body value, not a missing resource — the path id is what a `404` speaks to).
- **When `parent_id` is owned by a different user, Then** `403`.
- **When `parent_id` refers to a category that itself has a `parent_id`, Then** `400` — two levels only.
- **When the category being reparented itself has subcategories, Then** `400` — it can't become a child while it's a parent.
- **When `archived: true` and the category still has a non-archived subcategory, Then** `400` — archive or move the children first.
- **When `archived: false` and the category's parent is archived, Then** `400` — unarchive the parent first.
- **When `position` isn't an integer, Then** `400`.

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
- **Archive, not delete (006):** `Category.archived` (Boolean, default `false`). No delete endpoint — a deleted category would orphan the `category_id` on its transactions and allocations, losing history. Archived categories are filtered out of `GET /api/budget`'s `categories` list (returned in `archived_categories` instead) and excluded from `totals`. Enforced in `budget_api.py`, no DB constraint. Archiving a parent with a live child is a `400` (children first); unarchiving a child under an archived parent is a `400` (parent first).
- **Sibling ordering (006):** `Category.position` (already on the model, previously never written) is now the primary sort key for `GET /api/budget`, `(position, id)`. `PATCH /api/categories/<id>` with `position` moves a category within its `(user_id, parent_id)` sibling group; the handler re-packs the whole group to a gap-free `0..n-1` sequence on every reorder or reparent, so positions never collide or drift. A reparent lands the category at the end of its new group before any `position` in the same request is applied.
- **Month-bounded `available` + `rollover` (changes/025, supersedes the 006 cumulative rule below):** the budget is now genuinely separated by month. `available` for the viewed month `M` = `SUM(allocations WHERE month <= M) + SUM(signed transactions WHERE posted_at < first day of M+1)`; `rollover` = that minus this month's own allocation and spend = the carry-in from prior months. A category overspent in one month starts the next month with a negative `rollover`/`available` and must be re-funded; a leftover carries forward positively. `ready_to_assign` is likewise bounded to income through the end of `M` minus allocations for `M` and earlier, so assigning money to a future month doesn't shrink the current month's assignable pool. Overspending never reduces `ready_to_assign` — it stays contained in the category (user decision, 2026-08-31). No migration: `BudgetAllocation.month` and `Transaction.posted_at` already carry everything needed.
- **[Superseded by 025] `available` is cumulative, `spent_this_month` is month-scoped (006):** `available` = `SUM(all allocations for the category) + SUM(all signed transactions for the category)` — the rolled-over envelope balance, matching `ready_to_assign`'s cumulative semantics and `context/mvp-scope.md`'s "category balance rollover month to month." `spent_this_month` is the only per-category value re-scoped to the requested month. `totals` sums the per-category `allocated_this_month` / `spent_this_month` / `available` over non-archived categories only; parent and child are independent line items so there is no double-count.
- **Target progress (006):** `monthly_target_amount` keeps its 005 meaning (full target ÷ months, progress-blind) as a baseline. `needed_this_month` is the actionable number: for a dated goal (`yearly`/`custom`), `max(0, (target_amount − funded) ÷ months_remaining)` where `funded` is the category's current envelope balance (`max(0, available)`) — spending against the category lowers `funded`, so the monthly ask rises to compensate (YNAB's model). For a `monthly` goal, `funded` is `allocated_this_month` and `needed_this_month` is `max(0, target_amount − funded)`. `progress` = `min(1, funded ÷ target_amount)`.
- **Credit-card payment categories (021):** connecting a `type == "credit"`
  account auto-creates a `Category` with `payment_account_id` set (unique
  FK → `account.id`), under a dedicated top-level `"Credit Card Payments"`
  group (see `spec/plaid-sync.md`). `GET /api/budget` gives every entry
  `is_payment_category` + `payment_account_id`; a payment entry also carries
  `card_spending_this_month` / `card_payments_this_month` (month-scoped,
  positive) + `card_balance` (the card's negative balance), with
  `spent_this_month = "0"` and `target = null`.
  Its `available` is the cash set aside to pay the card down:
  `Σ(allocations to P) + moved_in(P) − cc_payments(P) + cc_opening(P)` where
  `moved_in` = card outflows filed to a *normal* (non-payment) category
  (Σ of `−amount`), `cc_payments` = transfer inflows onto the card, and
  `cc_opening` = the card's synthetic negative `"Starting Balance"`. The
  card **purchase still counts as spend in its own spending category** — it
  is *not* also subtracted here; the two net out in `totals.available` (one
  envelope down, the payment envelope up). `totals.spent` **skips** payment
  categories; `totals.budgeted` / `totals.available` include them.
  `ready_to_assign` is unaffected (the moves touch neither `is_income` rows
  nor allocations). The `"Credit Card Payments"` group rolls its children
  up via the existing 014 mechanism (adjustments are folded into each
  child's `available` before the roll-up).
  **Guards:** assigning a transaction to a payment category → `400`
  (`spec/transactions.md`); `PATCH /api/categories/<id>` changing
  `name` / `parent_id` / `archived` on one → `400` (`position` allowed);
  `POST .../allocations` to one is **allowed** (that's how you fund payoff).

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

- `tests/test_budget_api.py` § `"test_get_budget_ready_to_assign_counts_is_income_minus_allocations"` — covers § GET /api/budget: `ready_to_assign` = `SUM(Transaction.amount WHERE is_income) − SUM(BudgetAllocation.allocated_amount)`.
- `tests/test_budget_api.py` § `"test_get_budget_ready_to_assign_excludes_plain_uncategorized_inflow"` — covers § GET /api/budget: an uncategorized inflow *not* marked `is_income` no longer counts toward `ready_to_assign` (the semantic change from the old uncategorized-inflow formula).
- `tests/test_budget_api.py` § `"test_get_budget_category_without_target_has_null_target"` — covers § GET /api/budget: per-category `target` is `null` when no active target exists.
- `tests/test_budget_api.py` § `"test_get_budget_category_with_active_target_includes_target_shape"` — covers § GET /api/budget: per-category `target` carries `target_type`/`target_amount`/`target_date`/`monthly_target_amount` when an active target exists.

4 new tests confirmed red before commit — the old formula returns `1350`/`500` where the new one expects `850`/`0`, and `target` is absent from the per-category shape. The paired `is_income` toggle tests for `spec/transactions.md` live in `tests/test_transactions.py` (see that spec's Tests section).

- `tests/test_budget_api.py` § `PATCH /api/categories/<id>` section (`test_patch_category_*`, 006) — covers rename (ok / duplicate `409` / empty `400`), reparent (under top-level / to `null` / self `400` / under a subcategory `400` / a category with children `400` / another user's parent `403`), archive (ok / parent-with-active-child `400`), unarchive (ok / child-under-archived-parent `400`), archived split (absent from `categories`, present in `archived_categories`), `position` reorder + gap-free re-pack, and the `401` / `404` / `403` / empty-body `400` cases.
- `tests/test_budget_api.py` § `GET /api/budget` 006 additions (`test_get_budget_spent_this_month_*`, `test_get_budget_totals_*`, `test_get_budget_*target_needed_this_month*`, `test_get_budget_monthly_target_months_remaining_is_one`) — covers month-scoped `spent_this_month`, `totals` summing active categories only, and the target progress fields (`months_remaining`, `funded`, `needed_this_month`, `progress` clamp).

- `tests/test_budget_api.py` § changes/025 additions — `test_get_budget_available_excludes_later_month_activity` (later-month allocations/transactions invisible from the viewed month), `test_get_budget_rollover_carries_prior_month_leftover` / `test_get_budget_overspend_rolls_negative_into_next_month` (the `rollover` field, positive and negative), `test_get_budget_ready_to_assign_is_scoped_to_income_through_viewed_month` + `test_get_budget_future_allocation_does_not_reduce_current_month_ready_to_assign` (month-scoped `ready_to_assign`), `test_get_budget_totals_include_rollover`, `test_get_budget_group_rollover_sums_its_children`, `test_card_activity_after_the_viewed_month_is_excluded_from_payment_available`.

## Changes
- 001 (2026-08-10) — initial contract, second slice of `changes/001-api-spa-rewrite/plan.md`.
- 001 (2026-08-10) — built. New `budget_api.py` blueprint; old server-rendered routes, templates, and flask_wtf removed. All 19 tests green (36 total with auth.md's suite, no regressions).
- 005 (2026-08-26) — added § POST/GET /api/categories/<id>/target (category budget targets: monthly/yearly/custom, superseded-not-deleted history) and changed `ready_to_assign` to read `Transaction.is_income` instead of implicit uncategorized-inflow. Second half of `changes/005-budget-targets-and-tbb/plan.md`, paired with `spec/transactions.md`'s `is_income` toggle. Not yet built.
- 005 (2026-08-26) — § POST/GET /api/categories/<id>/target built. New `CategoryTarget` model + migration (`e6875d83ae67`); `budget_api.py` gains `set_target`/`get_target`. All 22 target tests green, 92/92 full suite (9 skipped — Plaid sandbox tests requiring real credentials). `ready_to_assign`/`is_income` half of this slice (second half, paired with `spec/transactions.md`) not yet built — status stays `in-progress`.
- 005 (2026-08-26) — `ready_to_assign`/`is_income` + budget-view `target` tests locked: 4 tests in `tests/test_budget_api.py`, all confirmed red. Depends on `spec/transactions.md`'s new `Transaction.is_income` column + migration `a1b2c3d4e5f6` (added with that spec's test commit). No `get_budget` logic changed — `ready_to_assign` still uses the old uncategorized-inflow formula and the per-category shape still omits `target`; the build closes both. Status stays `in-progress`.
- 005 (2026-08-26) — built. `get_budget`: `ready_to_assign` now sums `Transaction.amount` where `is_income` is true (joined through the user's accounts) minus total allocated; each per-category entry gains a `target` field (`null`, or the active `CategoryTarget` trimmed to `target_type`/`target_amount`/`target_date`/`monthly_target_amount`). All 4 tests green; 103/103 full suite (9 skipped — Plaid sandbox). Both halves of slice 005 built — spec status → built.
- 006 (2026-08-27) — added § `PATCH /api/categories/<id>` (rename / reparent / archive / reorder — no delete, categories are archived to keep transaction+allocation history); `GET /api/budget` now splits `categories` (active, ordered by `(position, id)`) from `archived_categories`, adds per-category `spent_this_month` / `position` / `archived`, a top-level `totals` object, and expands the `target` embed with `months_remaining` / `funded` / `needed_this_month` / `progress`. New `Category.archived` column + migration `b2c3d4e5f6a7`; `_month_bounds` moved from `transactions_api.py` to `api_helpers.py`. `changes/006-target-trackers-and-category-management/plan.md`. Built: `budget_api.py` gains `update_category` + `_pack_siblings` + `_target_budget_view`; 25 new tests in `tests/test_budget_api.py`; 128/128 full suite (9 skipped — Plaid sandbox). `monthly_target_amount` unchanged so the 005 target tests stay green. Status stays `built`.
- 014 (2026-08-27) — category groups. A top-level category with ≥1
  non-archived child becomes a group: `GET /api/budget` entry gets
  `"is_group": true` and sums its children's
  `allocated_this_month`/`spent_this_month`/`available` (+ the parent's own
  legacy amounts); `target` is null. `POST
  /api/categories/<id>/allocations` on a group → `400`. `totals` still
  sums each category's own values (no double-count). Reverses the "no
  roll-up" design in the line above. Also `spec/transactions.md`: assigning
  a transaction to a group → `400`. `budget_api.py` + `api_helpers.py`
  (`category_has_children`) + `transactions_api.py`; frontend
  `BudgetPage.tsx` (collapsible group row, no assign input, collapse state
  in `localStorage`) + `TransactionsPage.tsx` (groups out of the pickers).
  `tests/test_budget_api.py` +8, `tests/test_transactions.py` +2, e2e +1.
  Full suite 208 passed / 6 skipped.
- 019 (2026-08-27) — transfers excluded from budget math. `GET /api/budget`
  now filters `Transaction.transfer.is_(False)` out of `income_total`,
  `spent_total`, and `spent_this_month` — a movement between the user's own
  accounts (a bank transfer, or a credit-card payment) neither spends nor
  earns, so it must not touch `ready_to_assign`, a category's
  `spent_this_month`, or its `available`. Transfer rows still exist and
  still move each side's `Account.balance`. New `Transaction.transfer`
  column + migration `ca283921af94`; set on the Plaid path (see
  `spec/plaid-sync.md`). `tests/test_budget_api.py` +2.
- 021 (2026-08-27) — YNAB-style credit-card budgeting. `Category.payment_account_id`
  (nullable, unique FK → `account.id`, ON DELETE SET NULL) + migration
  `7eb728de0f4a`. `get_budget` folds a per-card `moved_in − cc_payments +
  cc_opening` adjustment into each payment category's `available` before the
  group roll-up; new response fields `is_payment_category` /
  `payment_account_id` / `card_spending_this_month` /
  `card_payments_this_month` / `card_balance`; `totals.spent` skips payment
  categories. Guards on `update_category` (name/parent/archived → 400) and
  transaction assignment (`spec/transactions.md`). `api_helpers.is_payment_category`
  + `infer_category_id` excludes payment envelopes. Starter tree drops the
  generic "Credit Card Payment" line. `tests/test_budget_api.py` +14,
  `tests/test_transactions.py` +2, `tests/test_plaid_sync.py` +2, conftest
  `credit_account` fixture; `BudgetPage.tsx` payment-row branch; e2e +1.
- 025 (2026-08-31) — month-separated budget. `GET /api/budget`'s `available`
  and `ready_to_assign` are now bounded to the viewed month instead of running
  all-time: `available` = `Σ(allocations WHERE month <= M) + Σ(signed txns WHERE
  posted_at < first-of-M+1)`; `ready_to_assign` = income through end of M minus
  allocations for M and earlier. New per-entry + `totals` field `rollover` = the
  carry-in from prior months (`available − allocated_this_month −
  spent_this_month`); a category overspent in one month starts the next negative
  and must be re-funded, and overspending never touches `ready_to_assign` (user
  decision). Credit-card fold (`_by_card`) bounded to `posted_at < end` too. No
  migration. `budget_api.py` `get_budget` only; `tests/test_budget_api.py` +9;
  frontend `BudgetPage.tsx` gains a prev/next month stepper (month in `?month=`)
  and a per-row rollover line, `client.ts` `BudgetCategory`/`BudgetTotals` gain
  `rollover`. `changes/025-monthly-budget`.
