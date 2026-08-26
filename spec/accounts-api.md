---
status: built
depends_on: [auth.md, plaid-connect.md]
---

# Accounts API: list connected bank accounts

## Does
Lets a user see their bank accounts (name, balance, available balance,
last-updated date) — the first UI surface for what `plaid-connect.md` and
`plaid-sync.md` actually populate. No new data model — `Account` already
exists and is already written by sync; this slice is the first thing that
reads it back out for the user.

## Done when
- A user can list their own accounts, seeing current balance and available
  balance for each.
- The demo user sees their synthetic seeded accounts (no Plaid connection
  required — accounts exist independent of `plaid_account_id`).
- Per-user data isolation holds — an account is only visible to its
  owning `user_id`.
- No Plaid identifiers (`plaid_account_id`) are exposed in the response —
  internal, not needed by any current UI.

## Integration test contract

### GET /api/accounts

**Setup:** An authenticated user with at least one account.
**Action:** `GET /api/accounts`, `Authorization: Bearer <access token>`.
**Input:** None.
**Expected output:** `200`, JSON `{"accounts": [{"id": ..., "name": ...,
"currency": ..., "balance": "...", "available_balance": "..." | null,
"balance_date": "..." | null}]}`. Only the authenticated user's own
accounts. `plaid_account_id` never appears in the response.

#### Error cases
- **When no/invalid access token, Then** `401`.

## Notes
- Reuses the direct `user_id` ownership-filter pattern already established
  in `budget_api.py`/`transactions_api.py` — no join-based ownership check
  needed since `Account.user_id` is direct (unlike `Transaction`, which
  goes through `Account`).
- `balance_date` is `None` for demo/synthetic accounts that have never
  been through a real sync — same nullability already on the column.

## Tests
- `tests/test_accounts_api.py` § `"test_list_accounts_returns_own_accounts"`
  — covers § GET /api/accounts contract.
- `tests/test_accounts_api.py` § `"test_list_accounts_only_shows_own_accounts"`
  — covers § per-user isolation.
- `tests/test_accounts_api.py` § `"test_list_accounts_without_token_returns_401"`
  — covers § error case: no token.
- `tests/test_accounts_api.py` § `"test_list_accounts_excludes_plaid_account_id"`
  — covers § Done-when: no Plaid identifiers leaked.

## Changes
- 005 (2026-08-26) — contract + build in one pass (small, additive,
  interactive session — not routed through the async plan-grill pipeline).
  All 4 tests confirmed red then green.
