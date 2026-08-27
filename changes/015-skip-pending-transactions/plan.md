# Slicing: skip pending transactions until they post

> Date: 2026-08-27
> Status: built
> Branch: changes/015-skip-pending-transactions

## What & Why
"Only pull transactions that have posted since the last successful sync."
The cursor already delivers only what's changed since last sync, so the
gap is **pending** transactions: Plaid sends them in `added` while they're
still unsettled, then again once they post. The user wants them held back
until they actually post — chosen over a rolling date cutoff, which would
permanently miss real transactions that banks post with an older
transaction date.

## Spec changes
- `spec/plaid-sync.md` — Changes entry: `added` / `modified` entries with
  `pending = true` are skipped and don't count; imported only once
  non-pending.

## Context changes
- None.

## Constraints
- **`_should_import(plaid_transaction, item)`** = `not pending AND
  _within_import_window(...)`. Replaces the bare `_within_import_window`
  call in both the `added` and `modified` loops of `_sync_one_item`.
- A skipped pending entry is **not counted** in `transactions_added` /
  `transactions_modified`.
- Nothing is permanently missed: when the transaction settles Plaid
  re-delivers it (same `transaction_id` as a `modified`, or a new `added`
  with `pending_transaction_id` pointing at the old one) and it's imported
  then — auto-categorization (013) applies to it as a new row.
- `removed` is untouched — a `removed` for a pending entry we never
  imported is already a no-op.
- Synced `Transaction` rows are consequently always `pending = false`. The
  model column and the "Pending" badge in `TransactionsPage` stay (cheap,
  and correct if a future source ever sets it) but are now inert for
  synced data.

## Non-Goals
- A rolling "since last sync date" cutoff (rejected — footgun).
- Surfacing `last_synced_at` more prominently in the UI (it's already on
  `GET /api/plaid/status` per 008).
- Removing the pending column / badge.

## Slices
- **015-A** backend — `plaid_api._should_import`; both sync loops use it.
  `tests/test_plaid_sync.py` +2 (a pending `added` is skipped while a
  settled one on the same page imports; a pending transaction imports on
  the later sync where it arrives non-pending).

## Verification
- `venv/bin/pytest` — 210 passed / 6 skipped (was 208/6).
- No frontend change; no e2e change (no e2e exercises Plaid sync).
- Live Sandbox `@requires_plaid_sandbox` sync tests unaffected (the
  `user_transactions_dynamic` data is settled) — run with real creds to
  confirm.
