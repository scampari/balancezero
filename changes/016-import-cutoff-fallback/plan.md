# Slicing: import-cutoff fallback (bug fix — sync pulled 3 months)

> Date: 2026-08-27
> Status: built
> Branch: changes/016-import-cutoff-fallback

## What & Why
A real connection (Capital One) pulled ~3 months / 221 transactions on its
first sync. Diagnosis: that `PlaidItem` was created before `changes/011`
added the `import_cutoff` column, so its `import_cutoff` was `NULL`, and
`_within_import_window` read `NULL` as "import everything." The 011
mechanism that was supposed to cap a fresh connection to recent
transactions never applied to it.

## Spec changes
- `spec/plaid-connect.md` / `spec/plaid-sync.md` — Changes entries: `NULL`
  `import_cutoff` falls back to `created_at`, never "import everything."

## Context changes
- None.

## Constraints
- **`_import_cutoff(item)` = `item.import_cutoff or item.created_at.date()`.**
  `_within_import_window` and `_add_starting_balance` both use it. A `NULL`
  cutoff can never again mean unbounded history — the worst case is "from
  the day the item row was created."
- **Migration `8c14d99893c5`** (`down_revision 24d3aed8ab6c`):
  `UPDATE plaid_item SET import_cutoff = created_at::date WHERE
  import_cutoff IS NULL`. `downgrade` is a no-op (can't recover which were
  NULL, and the value is harmless).
- `models.py` comment updated to drop the "NULL = import everything
  (backfilled rows)" claim.
- Applied to the dev DB: the Capital One item now has
  `import_cutoff = 2026-08-27` (its creation date).

## Non-Goals
- Removing the ~220 historical transactions that were already imported —
  that's a separate, destructive data cleanup, offered to the operator to
  confirm, not done here. (They are all uncategorized, so no user work is
  at stake.)
- Making `import_cutoff` `NOT NULL` at the DB level — the runtime fallback
  + backfill is enough, and keeping it nullable avoids a column rewrite.

## Slices
- **016-A** backend — `plaid_api._import_cutoff` + call sites; migration
  `8c14d99893c5`; `models.py` comment. `tests/test_plaid_sync.py`: the
  011 test that asserted "NULL imports all history" is replaced by
  `test_sync_null_cutoff_falls_back_to_the_items_creation_date` (a NULL
  cutoff + an old `created_at` → only post-creation transactions import);
  `_seed_item` now defaults `import_cutoff` to `date(2000,1,1)` so the
  many mock-sync tests that aren't about the cutoff still import their
  dated fixtures.

## Verification
- `venv/bin/pytest` — 210 passed / 6 skipped.
- `flask db upgrade` on the dev DB — the real item's `import_cutoff` is now
  set; its next sync will import nothing dated before the connect date.
- No frontend change.
