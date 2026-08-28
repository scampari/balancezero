# Slicing: link manually-added transactions to their synced duplicates

> Date: 2026-08-28
> Status: planning

## What & Why
A user who wants to keep their budget current can enter a transaction manually before it
posts at the bank (e.g. a payment made today that Plaid won't deliver for a few days).
Today the later sync creates a second `Transaction` row and the amount is double-counted
until the user notices and deletes one.
This change makes Plaid sync recognise the pre-entered manual row as the same transaction
and adopt it in place: the manual row gains the `plaid_transaction_id`, Plaid takes over
its money fields, and the user's `category_id` / `is_income` choices survive.

## Spec changes
- `spec/plaid-sync.md` — modified — the `added` / `modified` upsert path gains a
  manual-row adoption step before creating a new `Transaction`. New `transactions_linked`
  counter added to the per-item result objects and to `totals` (additive to the response
  shape locked in the `changes/008` rewrite and the § contract's "Expected output" JSON).
  New Notes entries: the match rule, the "Starting Balance" exclusion, and the accepted
  false-negative tradeoff of the strict (>= 0.8) similarity threshold.
- `spec/transactions.md` — modified — one-line correction: a manual row's
  `plaid_transaction_id` is no longer permanently `null`; a later Plaid sync can stamp it
  when it adopts the row (see `spec/plaid-sync.md`). Touches the § POST note near line 57
  and the Notes near line 80.

## Context changes
- None. No technology choice, integration pattern, or infrastructure commitment changes —
  this is a behavioural refinement of the existing Plaid sync slice.

## Constraints
- **Adoption happens inside `plaid_api._upsert_transaction`, in the `is_new` branch**,
  before `Transaction(...)` is constructed. This is the one place both the `added` and the
  `modified` loops in `_sync_one_item` funnel through, so a manual row that first meets its
  bank record via a `modified` entry (a pending entry held back by `changes/015`, then
  re-delivered non-pending) is adopted too.
- **Match rule** (all must hold):
  - same `account_id` as the incoming Plaid transaction's resolved account;
  - `Transaction.plaid_transaction_id IS NULL` (never already linked);
  - `amount` equals `-Decimal(str(plaid_txn["amount"]))` exactly — app convention,
    sign included, same negation the upsert already applies;
  - `abs(Transaction.posted_at - plaid_txn["date"]) <= 7 days`;
  - normalised description similarity `>= 0.8` via `difflib.SequenceMatcher`
    (lower-case, keep alphanumerics + single spaces); **no substring shortcut** — the
    user chose the strict variant knowing it will miss matches when the typed text
    differs a lot from the bank's merchant string.
- **The synthetic "Starting Balance" row is never a candidate** (`changes/012`) — exclude
  by its sentinel `description`. Belt-and-braces: the match rule alone already makes a
  collision astronomically unlikely (amount == full account balance, dated at
  `import_cutoff`, description fuzzy-matching "Starting Balance").
- **Multiple candidates → deterministic pick**: smallest date distance first, then highest
  similarity ratio, then lowest `id`. Exactly one manual row is adopted per incoming Plaid
  transaction; any other qualifying manual rows are left untouched.
- **Adoption preserves user intent**: only `amount`, `description`, `posted_at`, `pending`,
  `transfer` are overwritten from Plaid (the fields the upsert already owns).
  `category_id` and `is_income` are never touched — the same invariant that already
  protects a categorised synced row from a later `modified`.
- **Counting**: an adopted row increments `transactions_linked`, never
  `transactions_added` / `transactions_modified`. `_upsert_transaction` returns a signal
  (`"linked"`) so the caller in `_sync_one_item` picks the right counter.
  `transactions_linked` is added to `_EMPTY_COUNTERS` so the mutation-during-pagination
  reset (`plaid_api.py:504`) and the per-item `totals` accumulation both handle it with no
  extra code.
- **No migration.** `Transaction.plaid_transaction_id` is already nullable. Stamping a
  previously-null value cannot violate `uq_transaction_account_plaid_id` because adoption
  only runs when no row was found for that `(account_id, plaid_transaction_id)` in the
  first place.
- **New helper in `api_helpers.py`** for the normalised similarity check, with the `0.8`
  threshold as a named module constant and a comment recording the accepted tradeoff.
  Mirrors where `infer_category_id` already lives.
- **Idempotency**: once adopted, the row has a `plaid_transaction_id`, so every subsequent
  sync finds it by id on the normal path — no re-matching, no double count.

## Non-Goals
- No SimpleFIN work. `spec/simplefin-sync.md` is a superseded, never-built stub and there
  is no SimpleFIN sync code to change.
- No cleanup of *leftover* manual rows when the user entered two near-duplicates and only
  one matched — the unmatched one stays and the user deletes it, same as today.
- No fuzzy amount matching (a manual estimate that differs from the posted amount by a tip
  or FX). Exact amount only; a near-miss falls through to a normal new row.
- No UI change. Nothing in the transactions list distinguishes an adopted row from any
  other synced row (it is one, after adoption). No "linked" badge, no toast.
- No new e2e — no Playwright e2e exercises Plaid sync (`changes/015`).
- No back-fill or reconciliation of duplicate pairs that already exist in a user's data
  from before this change.

## Build skills
- None beyond the defaults. Pure backend Python in an established module with an
  established test file; `tdd` / `refactor` as normal in the build loop.

## First slice
- `spec/plaid-sync.md` — the only slice with a test contract to land. `spec/transactions.md`
  is a one-line documentation correction that rides along in the same commit; it has no new
  behaviour and no test of its own.

## Open Questions
- None blocking. The similarity threshold (`0.8`, no substring shortcut) and the new
  `transactions_linked` counter are both user-confirmed decisions.

## Test planning result (2026-08-28)

### Spec files modified
- `spec/plaid-sync.md` — added § "Manual-transaction adoption (changes/022)" to the
  `POST /api/plaid/sync` contract: match rule, ambiguity resolution, adoption effects,
  idempotency/removal, no-migration note, and 8 numbered offline cases. Added
  `transactions_linked` to the contract's "Expected output" JSON and to the `changes/008`
  rewrite note's response shape. Added a `## Tests` "no tests yet" pointer and a
  `## Changes` entry.
- `spec/transactions.md` — doc only: § POST note + Notes bullet + `## Changes` entry
  recording that a manual row's `plaid_transaction_id` can later be stamped by sync. No
  contract change, no new test.

### Mock boundaries
- Unchanged from the existing `plaid-sync` offline tests. `transactions_sync` mocked at
  the Plaid SDK layer; real Postgres, real `_upsert_transaction`, real `api_helpers`
  similarity helper. No `@requires_plaid_sandbox` test needed — matching is fully
  exercised offline.

### Context updates
- None.

### Test infrastructure notes
- New helper `api_helpers` description-similarity function needs its own unit tests
  (normalization; `0.80` threshold boundary — a pair just above and just below).
- No new fixtures beyond a seeded manual `Transaction` (no `plaid_transaction_id`) on a
  seeded Plaid-linked `Account`, which the existing offline harness already supports.
- `transactions_linked` must be added to `_EMPTY_COUNTERS` before the tests can assert on
  it in the per-item result and `totals`.
