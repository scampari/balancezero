---
status: in-progress
depends_on: [auth.md, budget-api.md]
---

# Transactions: list + categorize

## Does
Lets a user see their transactions and assign them to a budget category (or uncategorize them) — the missing MVP piece that makes the existing demo/seeded data actually interactive. No new data model — `Transaction` and its `category_id` FK already exist; this slice is the first thing that lets a user change `category_id` directly rather than only via `seed_demo.py`.

## Done when
- A user can list their transactions for a given month, seeing which category (if any) each one is assigned to.
- A user can assign or reassign a transaction to any of their own categories, or uncategorize it (`category_id: null`).
- Per-user data isolation holds: a transaction is reached through its account's ownership (`Transaction.account_id` → `Account.user_id`), not a direct `user_id` column on `Transaction` — there isn't one.
- A user can mark a transaction "To Be Budgeted" (`is_income: true`) instead of assigning it a category, feeding `budget-api.md`'s `ready_to_assign` computation explicitly rather than implicitly (`changes/005-budget-targets-and-tbb/plan.md`).

## Integration test contract

### GET /api/transactions

**Setup:** An authenticated user with at least one account, some transactions posted in the current month (a mix of categorized and uncategorized), and at least one transaction in a different month.
**Action:** `GET /api/transactions` (optionally `?month=YYYY-MM-01`), `Authorization: Bearer <access token>`.
**Input:** Optional `month` query param (ISO date, first of month). Defaults to the current month if omitted, same convention as `GET /api/budget`.
**Expected output:** `200`, JSON `{"month": "...", "transactions": [{"id": ..., "account_id": ..., "category_id": ..., "category_name": ..., "is_income": ..., "posted_at": "...", "amount": "...", "description": "...", "pending": ...}]}`. Only transactions posted within the requested month, only across the authenticated user's own accounts. `category_id`/`category_name` are `null` for uncategorized transactions. `is_income` is `true` only for transactions explicitly marked "To Be Budgeted" — always `false` for any transaction that has a `category_id`, by construction (mutual exclusivity, see § PATCH). Ordered most-recent-first.
**Side effects:** None (read-only).

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `month` is present but not a valid ISO date, Then** `400`.

### PATCH /api/transactions/<int:transaction_id>

**Setup:** An authenticated user owns the target transaction (via its account) and, if assigning a category, owns the target category too.
**Action:** `PATCH /api/transactions/<transaction_id>`, `Authorization: Bearer <access token>`.
**Input:** JSON `{"category_id": <id>}` to assign, `{"category_id": null}` to uncategorize, or `{"is_income": true, "category_id": null}` to mark "To Be Budgeted" (**changed this slice** — `is_income` toggle added).
**Expected output:** `200`, JSON `{"id": ..., "category_id": ..., "category_name": ..., "is_income": ...}` reflecting the new state.
**Side effects:** `Transaction.category_id` and/or `Transaction.is_income` updated. Setting `is_income: true` implicitly clears `category_id` to `null` (they're mutually exclusive — see error cases); setting a non-null `category_id` implicitly clears `is_income` to `false`.

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When the request body is missing both `category_id` and `is_income` keys entirely, Then** `400` (distinguishes "not provided" from "explicitly null"/`false`).
- **When `transaction_id` doesn't exist at all, Then** `404`.
- **When `transaction_id` exists but its account belongs to a different user, Then** `403`.
- **When `category_id` is a non-null value that doesn't exist at all, Then** `404`.
- **When `category_id` is a non-null value that exists but belongs to a different user, Then** `403`.
- **When `is_income: true` is sent together with a non-null `category_id`, Then** `400` — mutually exclusive, a transaction is either assigned to a category or marked "To Be Budgeted," never both.

## Notes
- Reuses the same 404-for-nonexistent / 403-for-wrong-owner IDOR pattern as `budget-api.md`'s `_get_owned_category`, extended to also cover transaction ownership (via a join through `Account`, not a direct column — `Transaction` has no `user_id` of its own).
- No transaction *creation* endpoint in this slice — transactions currently only come from `seed_demo.py` or (once built) SimpleFIN sync. Categorizing is the only mutation this slice adds.
- `pending` (boolean, already on the model — SimpleFIN's pending-transaction flag) is returned as-is; no special handling needed yet, but worth surfacing to the frontend now so `simplefin-sync.md` doesn't need a follow-up API change later.
- **`is_income` (005):** new `Transaction.is_income` boolean, default `false`. Deliberately a flag on the existing model, not an auto-created "To Be Budgeted" `Category` row — keeps the category table free of synthetic entries and reuses this same PATCH endpoint/dropdown rather than adding a new relationship type. Mutual exclusivity with `category_id` is enforced server-side on every write (see § PATCH error cases), so no query anywhere needs to defensively check both.
- **No per-transaction backfill; one-time starting-balance reconciliation instead (005, decided 2026-08-26):** existing transactions keep `is_income=false`. Separately, a one-off script (run once at ship time, not part of any API endpoint) creates exactly one synthetic `Transaction` per `Account` — `is_income: true`, `amount` = the account's current `balance`, `description: "Starting Balance"`, `category_id: null` — so `ready_to_assign` reflects money already in the bank without importing transaction history. See `changes/005-budget-targets-and-tbb/plan.md`'s Constraints. Does not repeat automatically for accounts connected after this ships — that's future scope for `plaid-connect.md`/`accounts-api.md`, not this slice.

## Tests
- `tests/test_transactions.py` § `"test_list_transactions_returns_current_month_for_authenticated_user"` — covers § GET /api/transactions contract.
- `tests/test_transactions.py` § `"test_list_transactions_shows_null_category_for_uncategorized"` — covers § GET contract, null-category shape.
- `tests/test_transactions.py` § `"test_list_transactions_with_explicit_month_param"` — covers § GET month param.
- `tests/test_transactions.py` § `"test_list_transactions_only_shows_own_accounts"` — covers § per-user isolation.
- `tests/test_transactions.py` § `"test_list_transactions_without_token_returns_401"` — covers § GET error case: no token.
- `tests/test_transactions.py` § `"test_list_transactions_invalid_month_returns_400"` — covers § GET error case: invalid month.
- `tests/test_transactions.py` § `"test_patch_transaction_assigns_category"` — covers § PATCH contract (assign).
- `tests/test_transactions.py` § `"test_patch_transaction_uncategorizes_with_null"` — covers § PATCH contract (uncategorize).
- `tests/test_transactions.py` § `"test_patch_transaction_without_token_returns_401"` — covers § PATCH error case: no token.
- `tests/test_transactions.py` § `"test_patch_transaction_missing_category_id_key_returns_400"` — covers § PATCH error case: missing key.
- `tests/test_transactions.py` § `"test_patch_nonexistent_transaction_returns_404"` — covers § PATCH error case: transaction not found. Passes even pre-implementation (Flask routing 404 coincides); not a real green until built.
- `tests/test_transactions.py` § `"test_patch_another_users_transaction_returns_403"` — covers § PATCH error case: wrong transaction owner.
- `tests/test_transactions.py` § `"test_patch_transaction_with_nonexistent_category_returns_404"` — covers § PATCH error case: category not found. Same pre-implementation-pass caveat as above.
- `tests/test_transactions.py` § `"test_patch_transaction_with_another_users_category_returns_403"` — covers § PATCH error case: wrong category owner.

12 of 14 confirmed red (404, no routes yet) before commit; the other 2 are documented above.

- `tests/test_transactions.py` § `"test_list_transactions_includes_is_income_false_for_normal_transaction"` — covers § GET: `is_income` present in the response shape, `false` for a categorized row.
- `tests/test_transactions.py` § `"test_list_transactions_shows_is_income_true_for_tbb_transaction"` — covers § GET: `is_income` is `true` for a transaction marked "To Be Budgeted."
- `tests/test_transactions.py` § `"test_patch_transaction_marks_is_income_true"` — covers § PATCH contract: `{"is_income": true, "category_id": null}` marks TBB; response body + `Transaction.is_income` side effect.
- `tests/test_transactions.py` § `"test_patch_is_income_true_clears_existing_category"` — covers § PATCH side effect: setting `is_income: true` implicitly clears a previously-assigned `category_id`.
- `tests/test_transactions.py` § `"test_patch_assigning_category_clears_is_income"` — covers § PATCH side effect: setting a non-null `category_id` implicitly clears `is_income` back to `false`.
- `tests/test_transactions.py` § `"test_patch_is_income_true_with_nonnull_category_returns_400"` — covers § PATCH error case: `is_income: true` together with a non-null `category_id` (mutually exclusive).
- `tests/test_transactions.py` § `"test_patch_assign_category_response_includes_is_income"` — covers § PATCH contract: the response shape gained `is_income`.

7 new `is_income` tests confirmed red before commit — `is_income` absent from both response shapes, the mutual-exclusivity request currently returns `200`, and the implicit-clear side effects don't happen yet.

## Changes
- 002 (2026-08-10) — initial contract, first slice of `changes/002-simplefin-and-transactions/plan.md`.
- 002 (2026-08-10) — built. New transactions_api.py. Refactor extracted _current_user_id/_parse_month (verbatim duplicates of budget_api.py's) into shared api_helpers.py. All 14 tests green, 50/50 full suite.
- 005 (2026-08-26) — added `is_income` toggle to § PATCH (mutually exclusive with `category_id`) and `is_income` to § GET's response shape — "To Be Budgeted." Second half of `changes/005-budget-targets-and-tbb/plan.md`, paired with `spec/budget-api.md`'s `ready_to_assign` change. Not yet built.
- 005 (2026-08-26) — `is_income` tests locked: 7 tests in `tests/test_transactions.py`, all confirmed red. New `Transaction.is_income` column (`models.py`) + migration `a1b2c3d4e5f6` added as test infrastructure — the routes already exist (built in 002), so unlike the `CategoryTarget` case there is no routing `404` to stand in for a missing column; the column must be real for the arrange/side-effect assertions to fail cleanly on values rather than `AttributeError`. No handler/formula logic touched — that's the build's job. Not yet built.
