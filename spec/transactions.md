---
status: built
depends_on: [auth.md, budget-api.md]
---

# Transactions: list + categorize

## Does
Lets a user see their transactions and assign them to a budget category (or uncategorize them) — the missing MVP piece that makes the existing demo/seeded data actually interactive. No new data model — `Transaction` and its `category_id` FK already exist; this slice is the first thing that lets a user change `category_id` directly rather than only via `seed_demo.py`.

## Done when
- A user can list their transactions for a given month, seeing which category (if any) each one is assigned to.
- A user can assign or reassign a transaction to any of their own categories, or uncategorize it (`category_id: null`).
- Per-user data isolation holds: a transaction is reached through its account's ownership (`Transaction.account_id` → `Account.user_id`), not a direct `user_id` column on `Transaction` — there isn't one.

## Integration test contract

### GET /api/transactions

**Setup:** An authenticated user with at least one account, some transactions posted in the current month (a mix of categorized and uncategorized), and at least one transaction in a different month.
**Action:** `GET /api/transactions` (optionally `?month=YYYY-MM-01`), `Authorization: Bearer <access token>`.
**Input:** Optional `month` query param (ISO date, first of month). Defaults to the current month if omitted, same convention as `GET /api/budget`.
**Expected output:** `200`, JSON `{"month": "...", "transactions": [{"id": ..., "account_id": ..., "category_id": ..., "category_name": ..., "posted_at": "...", "amount": "...", "description": "...", "pending": ...}]}`. Only transactions posted within the requested month, only across the authenticated user's own accounts. `category_id`/`category_name` are `null` for uncategorized transactions. Ordered most-recent-first.
**Side effects:** None (read-only).

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `month` is present but not a valid ISO date, Then** `400`.

### PATCH /api/transactions/<int:transaction_id>

**Setup:** An authenticated user owns the target transaction (via its account) and, if assigning a category, owns the target category too.
**Action:** `PATCH /api/transactions/<transaction_id>`, `Authorization: Bearer <access token>`.
**Input:** JSON `{"category_id": <id>}` to assign, or `{"category_id": null}` to uncategorize.
**Expected output:** `200`, JSON `{"id": ..., "category_id": ..., "category_name": ...}` reflecting the new state.
**Side effects:** `Transaction.category_id` updated.

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When the request body is missing the `category_id` key entirely, Then** `400` (distinguishes "not provided" from "explicitly null").
- **When `transaction_id` doesn't exist at all, Then** `404`.
- **When `transaction_id` exists but its account belongs to a different user, Then** `403`.
- **When `category_id` is a non-null value that doesn't exist at all, Then** `404`.
- **When `category_id` is a non-null value that exists but belongs to a different user, Then** `403`.

## Notes
- Reuses the same 404-for-nonexistent / 403-for-wrong-owner IDOR pattern as `budget-api.md`'s `_get_owned_category`, extended to also cover transaction ownership (via a join through `Account`, not a direct column — `Transaction` has no `user_id` of its own).
- No transaction *creation* endpoint in this slice — transactions currently only come from `seed_demo.py` or (once built) SimpleFIN sync. Categorizing is the only mutation this slice adds.
- `pending` (boolean, already on the model — SimpleFIN's pending-transaction flag) is returned as-is; no special handling needed yet, but worth surfacing to the frontend now so `simplefin-sync.md` doesn't need a follow-up API change later.

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

## Changes
- 002 (2026-08-10) — initial contract, first slice of `changes/002-simplefin-and-transactions/plan.md`.
- 002 (2026-08-10) — built. New transactions_api.py. Refactor extracted _current_user_id/_parse_month (verbatim duplicates of budget_api.py's) into shared api_helpers.py. All 14 tests green, 50/50 full suite.
