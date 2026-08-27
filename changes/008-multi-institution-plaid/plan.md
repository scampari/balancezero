# Slicing: full multi-institution Plaid

> Date: 2026-08-27
> Status: built
> Branch: changes/008-multi-institution-plaid

## What & Why
`context/plaid-integration.md` recorded single-institution-per-user as a
deliberate 004 scope choice ("`context/mvp-scope.md` never called for
multi-bank"). The user asked for multiple bank connections, so this slice
deliberately reverses that. The demo guarantee is untouched — the demo
user simply has no `plaid_items`.

## Spec changes
- `spec/plaid-connect.md` — modified — `PlaidItem` (1:many) replaces the
  three scalar `User.plaid_*` columns; `/connect` body gains
  `institution_name` / `institution_id`, upserts by `(user_id,
  plaid_item_id)`, reconnect updates in place; `/status` returns
  `{"items":[...]}` instead of `{"connected": bool}`; new
  `DELETE /api/plaid/items/<id>`. Status stays `built`.
- `spec/plaid-sync.md` — modified — `/sync` loops every `PlaidItem`, each
  with its own token + cursor + mutation-retry; response is per-item
  results + summed `totals` + an `ok` flag; all-items-fail → `502`,
  otherwise `200`; new `PlaidItem.last_synced_at` side effect;
  `_upsert_account` tags accounts with `plaid_item_id`. Sign-convention
  Notes unchanged. Status stays `built`.

## Context changes
- `context/plaid-integration.md` — the "Cardinality" / "Storage" / "Sync
  cursor scope" bullets updated: 008 reverses the single-institution scope
  at the user's request; `PlaidItem` model; cursor moves `User →
  PlaidItem`; demo guarantee unaffected.

## Constraints
- **`PlaidItem`**: `id`, `user_id` FK, `plaid_item_id` (String, **globally
  unique** — Plaid guarantees it; a cross-user re-exchange becomes an
  `IntegrityError` → `409`), `access_token_encrypted` (LargeBinary, **NOT
  NULL** now), `sync_cursor` (nullable — the old `User.plaid_sync_cursor`),
  `institution_name` / `institution_id` (nullable), `created_at`,
  `last_synced_at` (nullable).
- **`Account.plaid_item_id`** FK, **`ON DELETE SET NULL`**. Unlinking an
  institution keeps its accounts and transactions — deleting them would
  silently rewrite historical budget math and `changes/009` reports, and
  is irreversible. The accounts become inert "not linked" rows;
  reconnecting the same institution re-attaches them via
  `plaid_account_id` matching in `_upsert_account`.
- **Migration `035d62499d87`** (`down_revision='33d384c0c915'`): create
  `plaid_item`, add `account.plaid_item_id` FK, backfill one row per user
  with a connection + point that user's accounts at it (pre-migration is
  one-item-per-user so unambiguous), then drop the three `user.plaid_*`
  columns. `downgrade` re-adds them and copies back the earliest item per
  user (lossy for >1 item — dev-only). **Verified** on a scratch dev DB
  with a legacy-shaped row: upgrade → downgrade → upgrade clean, backfill
  correct.
- **`/sync` partial-failure semantics**: one institution's outage must not
  abort the others. Each item's per-page commits stand; its cursor is
  where the last committed page left off (a retried sync resumes safely).
  Response: `{"items":[{id,institution_name,status,error?,<counts>}],
  "totals":{<summed counts>}, "ok": <all ok>}`. `200` if ≥1 item synced,
  `502` only if every one failed, `409` if there are no items, `403` for
  demo.
- **`DELETE /api/plaid/items/<id>`**: demo → `403`; not found → `404`;
  not the caller's → `403` (direct `item.user_id != user.id`, the
  `security-requirements.md` IDOR pattern). Best-effort Plaid
  `/item/remove` (try/except — local cleanup never blocks on Plaid).

## Non-Goals
- Link update-mode (`?item_id=` to repair a broken item without a full
  re-Link) — noted as a follow-up.
- Grouping the Accounts grid by institution — the data (`account.
  plaid_item_id`) is exposed; the UI keeps a flat grid for now.
- A "remove the accounts too" action — SET NULL keeps them; the
  cascade-delete alternative is a possible future explicit action.
- `budget_api` / `transactions_api` / `accounts_api` behavior — they
  already aggregate across all of a user's accounts; only `accounts_api`
  gains a `plaid_item_id` field in its serializer.

## Slices
- **008-A** backend — `models.py` (`PlaidItem`, `Account.plaid_item_id`,
  drop `User.plaid_*`), migration, `plaid_api.py` rewrite
  (`_sync_one_item` extraction, per-item loop, `_item_summary`, `DELETE`
  route), `accounts_api.py` serializer. `conftest.py` `plaid_item`
  fixture; `tests/test_plaid_connect.py` + `tests/test_plaid_sync.py`
  rewrites.
- **008-B** frontend — `client.ts` (`PlaidInstitution`,
  `PlaidSyncItemResult`, new `PlaidSyncResult`, `removePlaidItem`,
  `connectPlaid` institution arg, `Account.plaid_item_id`),
  `ConnectBankButton.tsx` (institution metadata, `hasItems` prop),
  `AccountsPage.tsx` (linked-institutions list + Remove + partial-sync
  UI). e2e `plaid-institutions.spec.ts` + `seed_e2e_plaid.py`.

## Verification
- `venv/bin/pytest` — 162 passed / 5 skipped (was 149/9; several
  `@requires_plaid_sandbox` tests became offline mocked tests).
- Migration upgrade/downgrade/upgrade clean with a legacy row (above).
- `cd frontend && npm run build && npm run lint` clean.
- `npm run test:e2e` — 19 passed (17 prior + 2 new).
- Live-Sandbox tests (`@requires_plaid_sandbox`, run with real creds):
  connect one institution, connect a second, `/status` lists both,
  per-item sync — pending a run with `.env` creds exported.
