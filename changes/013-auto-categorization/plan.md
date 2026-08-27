# Slicing: auto-categorization by prior choice

> Date: 2026-08-27
> Status: built
> Branch: changes/013-auto-categorization

## What & Why
Categorizing every synced transaction by hand is the main chore. The user
wants a new transaction to pick up the category the same merchant got last
time.

## Spec changes
- `spec/transactions.md` — § POST auto-fills `category_id` from prior when
  omitted; Changes entry.
- `spec/plaid-sync.md` — Changes entry: `_upsert_transaction` auto-fills a
  new row's category.

## Context changes
- None.

## Constraints
- **Match: exact `Transaction.description`** (Plaid's merchant `name`),
  per user, across all their accounts. Pick the category from the *most
  recent categorized* transaction with that description
  (`ORDER BY posted_at DESC, id DESC`). No fuzzy matching, no
  normalization — exact is predictable and cheap.
- **Only fills a blank.** Applied when a brand-new transaction has
  `category_id IS NULL` and `is_income` is false. Never overrides an
  explicit category, an existing row's category, or a "To Be Budgeted"
  flag. A `modified` sync upsert never re-categorizes.
- **Prior matches are real user choices only.** The lookup filters
  `category_id IS NOT NULL`, so a prior transaction marked TBD
  (`category_id` null) is not a match, and `is_income` is never
  propagated — only real categories.
- **Shared helper:** `api_helpers.infer_category_id(user_id, description,
  cache=None)`. `cache` is an optional `description -> category_id` dict
  the caller reuses across a batch; `_sync_one_item` passes one so each
  distinct merchant is looked up once per sync. `POST /api/transactions`
  calls it without a cache (single row).
- **An auto-filled category counts as a real category** for the *next*
  transaction — the cache holds the pre-sync answer, so all same-merchant
  new rows in one sync get the same category, and a later separate sync
  sees the now-categorized rows normally.

## Non-Goals
- Learning rules / ML / merchant-name normalization / regex rules.
- Auto-propagating "To Be Budgeted".
- A UI to review or bulk-apply suggestions — the category just arrives
  pre-filled and is one dropdown change to override.
- Re-categorizing historical uncategorized transactions in bulk.

## Slices
- **013-A** backend — `api_helpers.infer_category_id`; `plaid_api.py`
  (`_upsert_transaction` new-row auto-fill + per-sync cache in
  `_sync_one_item`); `transactions_api.py` (`create_transaction` fills a
  blank `category_id`). Tests: `tests/test_plaid_sync.py` +2,
  `tests/test_transactions.py` +3.
- **013-B** — no frontend code change (server returns the category; the
  table renders it). e2e `transactions.spec.ts` +1: add a categorized
  "AUTOCAT DELI", then add another with no category → both rows show the
  category.

## Verification
- `venv/bin/pytest` — 200 passed / 6 skipped (was 195/6).
- `cd frontend && npm run build && npm run lint` clean (2 pre-existing
  warnings).
- `npm run test:e2e` — 24 passed (23 prior + 1).
