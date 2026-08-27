# Slicing: transaction editing + fresh-connection import cutoff

> Date: 2026-08-27
> Status: built
> Branch: changes/011-transaction-editing-and-import-cutoff

## What & Why
Three user-reported issues:

1. **Bug:** once a transaction is set to "To Be Budgeted" it can't be moved
   back to plain Uncategorized. Root cause: the "Uncategorized" dropdown
   choice sends `PATCH {"category_id": null}`, and `patch_transaction` only
   cleared `is_income` when a *non-null* category was assigned — so the row
   stayed `is_income = true` forever.
2. **Manual transactions:** no way to add or delete a transaction by hand.
3. **Import cutoff:** a fresh Plaid connection pulls ~90 days of history;
   the user wants only transactions that post *after* connecting.

## Spec changes
- `spec/transactions.md` — modified — § PATCH: a `category_id` key of `null`
  (not just a real id) now clears `is_income` unless the request also sets
  `is_income`. New § POST /api/transactions (manual add) and
  § DELETE /api/transactions/<id>. Status stays `built`.
- `spec/plaid-connect.md` / `spec/plaid-sync.md` — Changes entries for the
  `PlaidItem.import_cutoff` column and the sync filter.

## Context changes
- None. `import_cutoff` is a scoped rule on the existing `PlaidItem`, not a
  new architectural pattern.

## Constraints
- **PATCH fix:** `if has_category and not has_is_income: is_income = False`.
  Any categorization action — assign a category OR explicitly choose
  "Uncategorized" — is exclusive with "To Be Budgeted". An explicit
  `{"is_income": true, "category_id": null}` still marks TBB (the body sets
  `is_income`).
- **`POST /api/transactions`** requires one of the user's own `Account`s
  (the model's `account_id` is `NOT NULL`). Body: `account_id`, `posted_at`
  (ISO date), `amount` (signed decimal — negative = spend), `description`,
  optional `category_id`. `is_income` is always `false` on create;
  `plaid_transaction_id` stays `null`. Full 400/403/404 matrix. `201`.
- **`DELETE /api/transactions/<id>`** — any owned transaction, manual or
  synced. A synced one can reappear if Plaid later reports it `modified`
  (accepted — documented). `200 {"status":"deleted"}`.
- **`PlaidItem.import_cutoff`** (Date, nullable). `/connect` sets it to
  `date.today()` on a **new** item only — a re-link (token repair) leaves
  it. `_sync_one_item` skips `added`/`modified` transactions dated before
  the cutoff. `NULL` cutoff (backfilled 008-era rows, and anything from
  before this change) = import everything, so no history that a user has
  already categorized gets retroactively hidden. `removed` is unaffected
  (a no-op for anything never imported). Migration `24d3aed8ab6c`.
- **Frontend:** `TransactionsPage` gains an "Add transaction" form (account
  / date / amount / description / category; disabled with a hint when the
  user has no accounts) and a per-row `✕` delete button.

## Non-Goals
- Editing an existing transaction's amount / date / description (only
  category / TBB, plus add + delete).
- Bulk delete; undo.
- A configurable per-user "import history back to X days" — the cutoff is
  the connect date, full stop.
- Manual accounts (add-account UI) — a manual transaction still needs an
  existing account.

## Slices
- **011-A** backend — `transactions_api.py` (PATCH fix + POST + DELETE);
  `models.py` `PlaidItem.import_cutoff` + migration; `plaid_api.py`
  (`/connect` sets cutoff, `_within_import_window` filter in
  `_sync_one_item`). Tests: `tests/test_transactions.py` (+11),
  `tests/test_plaid_sync.py` (+2), `tests/test_plaid_connect.py` (+2).
- **011-B** frontend — `client.ts` (`createTransaction`,
  `deleteTransaction` + wrappers); `TransactionsPage.tsx` (add form,
  delete button, fetch accounts). e2e `transactions.spec.ts` (+2:
  TBB→Uncategorized round trip, add + delete).

## Verification
- `venv/bin/pytest` — 192 passed / 6 skipped (was 177/5).
- Migration `flask db upgrade` on the dev DB — clean.
- `cd frontend && npm run build && npm run lint` — clean (2 pre-existing
  `only-export-components` warnings).
- `npm run test:e2e` — 23 passed (21 prior + 2). One pre-existing
  cross-spec flake in `budget-management` (reorder) failed once in a full
  run and passed on rerun and standalone — unrelated to this slice.
- Live-Sandbox: `test_connect_sets_import_cutoff_to_today` is
  `@requires_plaid_sandbox` — run with real creds to exercise it.
