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
- A user can mark a transaction "To Be Budgeted" (`is_income: true`) instead of assigning it a category, feeding `budget-api.md`'s `ready_to_assign` computation explicitly rather than implicitly (`changes/005-budget-targets-and-tbb/plan.md`).

## Integration test contract

### GET /api/transactions

**Setup:** An authenticated user with at least one account, some transactions posted in the current month (a mix of categorized and uncategorized), and at least one transaction in a different month.
**Action:** `GET /api/transactions` (optionally `?month=YYYY-MM-01` **or** `?since=YYYY-MM-DD`), `Authorization: Bearer <access token>`.
**Input:** Two mutually-exclusive optional filters:
- `since` (ISO date) — a **rolling window** (changes/027): every transaction posted **on or after** that date, no upper bound. This is what the frontend transactions page uses (a fixed number of days back from the viewer's *local* today), so entries don't vanish the instant a calendar month rolls over.
- `month` (ISO date, first of month) — a single calendar month, same convention as `GET /api/budget`.
- If both are given, `since` wins. If neither is given, defaults to the current month (server-local).
**Expected output:** `200`, JSON `{<echo>, "transactions": [{"id": ..., "account_id": ..., "category_id": ..., "category_name": ..., "is_income": ..., "posted_at": "...", "amount": "...", "description": "...", "pending": ...}]}` where `<echo>` is `"since": "YYYY-MM-DD"` when the `since` filter was used, otherwise `"month": "YYYY-MM-01"`. Only transactions matching the filter, only across the authenticated user's own accounts. `category_id`/`category_name` are `null` for uncategorized transactions. `is_income` is `true` only for transactions explicitly marked "To Be Budgeted" — always `false` for any transaction that has a `category_id`, by construction (mutual exclusivity, see § PATCH). Ordered most-recent-first.
**Side effects:** None (read-only).

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `month` is present but not a valid ISO date, Then** `400`.
- **When `since` is present but not a valid ISO date, Then** `400`.

### PATCH /api/transactions/<int:transaction_id>

**Setup:** An authenticated user owns the target transaction (via its account) and, if assigning a category, owns the target category too.
**Action:** `PATCH /api/transactions/<transaction_id>`, `Authorization: Bearer <access token>`.
**Input:** JSON `{"category_id": <id>}` to assign, `{"category_id": null}` to uncategorize, or `{"is_income": true, "category_id": null}` to mark "To Be Budgeted" (**changed this slice** — `is_income` toggle added).
**Expected output:** `200`, JSON `{"id": ..., "category_id": ..., "category_name": ..., "is_income": ...}` reflecting the new state.
**Side effects:** `Transaction.category_id` and/or `Transaction.is_income` updated. Setting `is_income: true` implicitly clears `category_id` to `null` (they're mutually exclusive — see error cases); **any `category_id` in the body — a real id OR an explicit `null` — implicitly clears `is_income` to `false` unless the same request also sets `is_income`** (changes/011). Without the `null` case, a transaction marked "To Be Budgeted" could never be moved back to plain uncategorized.

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When the request body is missing both `category_id` and `is_income` keys entirely, Then** `400` (distinguishes "not provided" from "explicitly null"/`false`).
- **When `transaction_id` doesn't exist at all, Then** `404`.
- **When `transaction_id` exists but its account belongs to a different user, Then** `403`.
- **When `category_id` is a non-null value that doesn't exist at all, Then** `404`.
- **When `category_id` is a non-null value that exists but belongs to a different user, Then** `403`.
- **When `is_income: true` is sent together with a non-null `category_id`, Then** `400` — mutually exclusive, a transaction is either assigned to a category or marked "To Be Budgeted," never both.

### POST /api/transactions  (changes/011 — manual add)

**Setup:** An authenticated user who owns at least one `Account` (and the
category, if one is given).
**Action:** `POST /api/transactions`, `Authorization: Bearer <access token>`.
**Input:** JSON `{"account_id": <id>, "posted_at": "YYYY-MM-DD", "amount":
"<decimal>", "description": "<text>", "category_id": <id>?}`.
**Expected output:** `201`, the created transaction in the same shape as a
`GET /api/transactions` row. `is_income` is always `false` on creation;
`plaid_transaction_id` is `null` on creation — but no longer permanently:
a later `/transactions/sync` can **adopt** this row when the bank posts the
matching transaction, stamping `plaid_transaction_id` in place rather than
inserting a duplicate (see `spec/plaid-sync.md` § Manual-transaction
adoption, `changes/022`). Sign follows the app convention — negative =
spending, positive = inflow. **When `category_id` is omitted (changes/013), it is auto-filled
from the category on the user's most recent transaction with the exact
same `description` — an explicit `category_id` in the body always wins.**
**Side effects:** One `Transaction` row created under the given account.

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When `account_id`, `posted_at`, `amount`, or `description` is missing,
  Then** `400`.
- **When `posted_at` is not an ISO date, or `amount` is not a number,
  Then** `400`.
- **When the account isn't found, Then** `404`; **when it belongs to
  another user, Then** `403`. Same for `category_id` when supplied.

### DELETE /api/transactions/<int:transaction_id>  (changes/011)

**Setup:** An authenticated user who owns the target transaction (via its
account).
**Action:** `DELETE /api/transactions/<transaction_id>`.
**Expected output:** `200`, JSON `{"status": "deleted"}`.
**Side effects:** The `Transaction` row is deleted. Works for any owned
transaction, manual or Plaid-synced — a synced one *can* reappear if a
later `/transactions/sync` reports it as `modified` (accepted: if Plaid
still has it and changes it, you probably want it back).

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When the transaction isn't found, Then** `404`.
- **When it belongs to another user, Then** `403` (and it is not deleted).

## Notes
- Reuses the same 404-for-nonexistent / 403-for-wrong-owner IDOR pattern as `budget-api.md`'s `_get_owned_category`, extended to also cover transaction ownership (via a join through `Account`, not a direct column — `Transaction` has no `user_id` of its own).
- No transaction *creation* endpoint in the 002/005 slices — transactions came only from `seed_demo.py` or Plaid sync. **changes/011 adds manual `POST` and `DELETE`** (see the contract sections above).
- **changes/022:** a manually created row is no longer guaranteed to keep `plaid_transaction_id == null` for its whole life. Plaid sync will link it to the real transaction once that posts (same account, exact amount, `posted_at` within 7 days, strict description match) — the contract for that lives in `spec/plaid-sync.md`, not here. Nothing about `POST`/`DELETE`/`PATCH` behavior changes.
- `pending` (boolean, already on the model — SimpleFIN's pending-transaction flag) is returned as-is; no special handling needed yet, but worth surfacing to the frontend now so `simplefin-sync.md` doesn't need a follow-up API change later.
- **`is_income` (005):** new `Transaction.is_income` boolean, default `false`. Deliberately a flag on the existing model, not an auto-created "To Be Budgeted" `Category` row — keeps the category table free of synthetic entries and reuses this same PATCH endpoint/dropdown rather than adding a new relationship type. Mutual exclusivity with `category_id` is enforced server-side on every write (see § PATCH error cases), so no query anywhere needs to defensively check both.
- **No per-transaction backfill; one-time starting-balance reconciliation instead (005, decided 2026-08-26):** existing transactions keep `is_income=false`. Separately, a one-off script (run once at ship time, not part of any API endpoint) creates exactly one synthetic `Transaction` per `Account` — `is_income: true`, `amount` = the account's current `balance`, `description: "Starting Balance"`, `category_id: null` — so `ready_to_assign` reflects money already in the bank without importing transaction history. See `changes/005-budget-targets-and-tbb/plan.md`'s Constraints. **changes/012 makes this automatic:** the first time `/transactions/sync` sees a Plaid account it doesn't have locally, it creates exactly that synthetic `Transaction` (`is_income: true`, `amount` = the account's `balance`, `description: "Starting Balance"`, dated at the connection's import cutoff), so `ready_to_assign` picks up money already in the bank even though the import cutoff means no pre-connection history is pulled. Only on account *creation* — re-syncing never adds a second one — and skipped for a zero balance. See `spec/plaid-sync.md`.

## Tests
- `tests/test_transactions.py` § `"test_list_transactions_returns_current_month_for_authenticated_user"` — covers § GET /api/transactions contract.
- `tests/test_transactions.py` § `"test_list_transactions_shows_null_category_for_uncategorized"` — covers § GET contract, null-category shape.
- `tests/test_transactions.py` § `"test_list_transactions_with_explicit_month_param"` — covers § GET month param.
- `tests/test_transactions.py` § `"test_list_transactions_only_shows_own_accounts"` — covers § per-user isolation.
- `tests/test_transactions.py` § `"test_list_transactions_without_token_returns_401"` — covers § GET error case: no token.
- `tests/test_transactions.py` § `"test_list_transactions_invalid_month_returns_400"` — covers § GET error case: invalid month.
- `tests/test_transactions.py` § `"test_list_transactions_since_returns_rolling_window"` — covers § GET `since` filter: on-or-after, no upper bound, echoes `since` not `month` (changes/027).
- `tests/test_transactions.py` § `"test_list_transactions_since_takes_precedence_over_month"` — covers § GET both-filters precedence.
- `tests/test_transactions.py` § `"test_list_transactions_invalid_since_returns_400"` — covers § GET error case: invalid `since`.
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
- 005 (2026-08-26) — built. `transactions_api.py`: `_serialize` gains `is_income`; `patch_transaction` accepts an `is_income` toggle, rejects `is_income: true` + non-null `category_id` with `400`, and applies the two implicit clears (marking `is_income` clears `category_id`, assigning a category clears `is_income`). All 7 tests green; 103/103 full suite (9 skipped — Plaid sandbox). Spec status → built.
- 011 (2026-08-27) — bug fix + manual editing. § PATCH: a `category_id`
  key of `null` now also clears `is_income` (a TBB transaction can be
  moved back to plain uncategorized — it couldn't before). New
  § POST /api/transactions (manual add, requires an owned account) and
  § DELETE /api/transactions/<id>. `transactions_api.py` +
  `tests/test_transactions.py` (11 new); `TransactionsPage.tsx` gains an
  add form + per-row delete; e2e `transactions.spec.ts` (+2). Full suite
  192 passed / 6 skipped. See `changes/011-transaction-editing-and-import-cutoff/plan.md`.
- 013 (2026-08-27) — auto-categorization by reuse. `POST /api/transactions`
  auto-fills `category_id` (when omitted) from the user's most recent
  transaction with the same `description`. Shared helper
  `api_helpers.infer_category_id` — see `spec/plaid-sync.md` for the sync
  side. Never overrides an explicit category or an existing row's category.
  `tests/test_transactions.py` +3.
- 014 (2026-08-27) — a category that is a group (has non-archived children)
  can't hold transactions: `PATCH` and `POST /api/transactions` with such a
  `category_id` → `400`. Auto-categorization (013) skips group categories
  too. See `spec/budget-api.md`.
- 019 (2026-08-27) — `Transaction.transfer` (Boolean, default false).
  Migration `ca283921af94`. Set on the Plaid sync path from the
  transaction's `personal_finance_category.primary`
  (`TRANSFER_IN` / `TRANSFER_OUT` / `LOAN_PAYMENTS`); manual transactions
  are always false. Surfaced in the `GET /api/transactions` serializer as
  `transfer` and badged on the Transactions page. Budget math excludes
  transfers — see `spec/budget-api.md`. `tests/test_plaid_sync.py` +1, e2e +1.
- 021 (2026-08-27) — a credit-card *payment* category (auto-created,
  `payment_account_id` set) can't hold transactions: `PATCH` and
  `POST /api/transactions` with such a `category_id` → `400`.
  Auto-categorization skips them too. See `spec/budget-api.md`.
  `tests/test_transactions.py` +2.
- 022 (2026-08-28) — doc only: a manually added row's `plaid_transaction_id`
  is no longer permanently `null` — Plaid sync can adopt the row when the
  real transaction posts. Behavior + contract live in `spec/plaid-sync.md`
  § Manual-transaction adoption; no endpoint behavior changes here, no new
  test in `tests/test_transactions.py`.
- 027 (2026-09-01) — `GET /api/transactions` gains a `?since=YYYY-MM-DD`
  rolling-window filter (on-or-after, no upper bound); response echoes
  `since` instead of `month` when it is used. `month` still works and still
  the no-arg default. The frontend transactions page now requests a 60-day
  window anchored to the viewer's *local* today, so rows don't disappear
  when a calendar month rolls over (and the budget's "current month" is
  likewise computed from local time, not UTC — see `frontend/src/lib/dates.ts`).
  `transactions_api.py` `list_transactions` only; `tests/test_transactions.py`
  +3. `changes/027-local-time-and-rolling-transactions`.
