# Slicing: Starting Balance on a new connection

> Date: 2026-08-27
> Status: built
> Branch: changes/012-starting-balance-on-connect

## What & Why
`changes/011` made a fresh Plaid connection skip all pre-connection
history (the import cutoff). That's the behavior the user wanted, but it
means the money already sitting in the account never enters the budget —
`ready_to_assign` would ignore it. The user wants a connected account's
current balance to show up as Ready to Assign / a Starting Balance, which
is exactly the one-time reconciliation `spec/transactions.md`'s Notes
described in 005 as "future scope" — now due.

## Spec changes
- `spec/plaid-sync.md` — Changes entry: `_upsert_account` on account
  creation adds a synthetic "Starting Balance" transaction.
- `spec/transactions.md` — the 005 "one-time starting-balance
  reconciliation" Note updated: it's automatic on first sync now.

## Context changes
- None.

## Constraints
- **In `_upsert_account`, on account creation only.** `_add_starting_balance`
  inserts one `Transaction`: `is_income=true`, `amount = account.balance`
  (Plaid's `balances.current`), `description="Starting Balance"`,
  `category_id=null`, `plaid_transaction_id=null` (synthetic — not a Plaid
  row, so it isn't touched by future `added`/`modified`/`removed`),
  `posted_at = PlaidItem.import_cutoff or date.today()`.
- **Idempotent** — only when `account is None` before the upsert, so
  re-syncing an existing account never adds a second one.
- **Zero balance → skip.** No "$0.00 Starting Balance" clutter.
- **`seed_demo.py`**: the demo "Paycheck" transaction is now
  `is_income=true` so a freshly seeded demo has a sensible Ready to
  Assign. (Existing dev/demo databases are unaffected — the seed skips a
  user that already exists; re-seed to pick it up.)

## Non-Goals
- Retroactively adding a Starting Balance to accounts that already exist
  locally (008-backfilled connections, manually-created accounts) — only
  genuinely new accounts from a sync.
- Negative / credit-card balance handling beyond "store `account.balance`
  as-is" — a negative starting balance reduces `ready_to_assign`, which is
  defensible; not special-cased.
- A UI to edit or hide the Starting Balance row — it's an ordinary
  `is_income` transaction, editable/deletable via the 011 controls.

## Verification
- `venv/bin/pytest` — 195 passed / 6 skipped (was 192/6; +3
  starting-balance tests in `tests/test_plaid_sync.py`: created for a new
  account with amount == balance + is_income + no plaid id; no second one
  on re-sync; skipped for a zero balance).
- No frontend change — the row renders through the existing transactions
  table.
