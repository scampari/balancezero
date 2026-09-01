# Slicing: the transfer flag respects a user's category

> Date: 2026-09-01
> Status: built
> Branch: changes/028-transfer-flag-respects-category

## What & Why
Plaid auto-flags Venmo / Zelle / PayPal payments and Department-of-Education
(student loan) payments as `transfer` via `personal_finance_category.primary`
(`TRANSFER_OUT` / `LOAN_PAYMENTS`). changes/019 excludes every `transfer` row
from budget math, so these real expenses stayed invisible **even after the user
categorized them**.

Two-part fix:

1. **A categorized transaction always counts as spend** (`budget_api.py`). The
   per-category `spent_this_month` / `spent_through_end` and the credit-card
   `normal_card_spend` queries drop their `transfer.is_(False)` filter — they are
   already scoped to a `category_id`, so this only affects rows the user
   explicitly filed. `income_total` / `ready_to_assign` still ignore every
   `transfer` row (a categorized row can't be income — `is_income` and
   `category_id` are mutually exclusive).

2. **Narrow Plaid's transfer detection** (`plaid_api.py` `_is_transfer`). Read
   `personal_finance_category.detail`, not just `primary`:
   - `TRANSFER_IN` / `TRANSFER_OUT` → transfer, unless detail ends `_P2P`.
   - `LOAN_PAYMENTS` → transfer only for `LOAN_PAYMENTS_CREDIT_CARD_PAYMENT`.
   Re-sync overwrites `transfer` from the payload, so existing mis-flagged rows
   self-heal.

## Spec changes
- `spec/budget-api.md` — per-category spend bullet + `## Changes` 028.
- `spec/plaid-sync.md` — `_is_transfer` detail rules + `## Tests` + `## Changes` 028.

## Context changes / migration
None.

## Files
- `budget_api.py` `get_budget` — 3 `transfer.is_(False)` filters removed.
- `plaid_api.py` `_is_transfer` — detail-aware.
- `tests/test_budget_api.py` — `test_get_budget_excludes_transfer_transactions_from_a_category`
  flipped to `test_get_budget_counts_a_categorized_transfer_as_spend`.
- `tests/test_plaid_sync.py` — `test_sync_flags_transfers_from_personal_finance_category`
  expanded (P2P + student-loan → not a transfer; CC payment via detail → transfer).

## Verification
- `pytest` — 276 passed / 7 skipped.
- Manual: categorize a Plaid-flagged Venmo/loan payment → it appears in the
  category's Spent and lowers Available; on next Plaid sync a new Venmo/loan
  payment arrives with `transfer=false`.
