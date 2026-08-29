# Slicing: Add accounts at an already-connected bank (Plaid Link update mode)

> Date: 2026-08-28
> Status: building — contracts landed, ready for test-writer

## What & Why

Today the only way to link an account is a full Plaid Link run, which creates
(or in-place re-links) a `PlaidItem`.
A user who connected a bank but didn't authorize all of their accounts at that
bank, or who opened a new account there later, has no way to add it short of
removing and re-linking the whole institution.

Plaid Link's **update mode with account selection**
(`update.account_selection_enabled=true`) is built for exactly this: the user
re-opens Link for an existing Item, picks additional accounts, and the Item's
`access_token` is unchanged (no `public_token`, no exchange).
The newly-authorized accounts then flow in through the existing
`/api/plaid/sync` loop with no sync changes for the token flow itself.

Second half of the change: an account added months after the Item was first
linked should start tracking from the day it's added, not from the Item's
original connect date. That needs a per-account import cutoff.

## Spec changes

- `spec/plaid-connect.md` — modified — new route
  `POST /api/plaid/items/<int:item_id>/update-link-token`. Mints a link_token
  in update mode from the item's stored `access_token`
  (`update=LinkTokenCreateRequestUpdate(account_selection_enabled=True)`, **no
  `products`**, same `client_name` / `country_codes` / `language` / `user` /
  optional `redirect_uri` as `POST /link-token`). Ownership + guard behaviour
  mirrors `DELETE /api/plaid/items/<id>`: demo → `403`, unknown id → `404`,
  not the caller's → `403`, Plaid unreachable / rejects → `502` sanitized
  (`_GENERIC_PLAID_ERROR`), success → `200 {"link_token": "<token>"}`.
  No `/connect` or `/status` change — update mode returns no `public_token`,
  so there is nothing to exchange and no new `PlaidItem` is created.

- `spec/plaid-sync.md` — modified — new `Account.import_cutoff` (Date,
  nullable) and an **effective per-account cutoff**:
  - `_upsert_account` stamps `date.today()` on the row **only when it creates
    it for an Item that has synced before** (`is_new and item.last_synced_at
    is not None`); never on update, and never during the Item's first-ever
    sync (see Grill — keeps the "connect then sync later" path retry-safe).
  - A new `_account_import_cutoff(account, item)` returns
    `account.import_cutoff or _import_cutoff(item)` — so every row that
    predates this column (`NULL`) keeps exactly today's Item-level behaviour;
    no backfill migration.
  - `_should_import` / `_within_import_window` take the resolved `Account`
    (already available in both sync loops via `_account_for(...)`) and gate on
    the effective per-account cutoff instead of the Item's.
  - `_add_starting_balance` dates the synthetic opening row at the account's
    effective cutoff (so an account added later gets a Starting Balance dated
    its add-date, not the Item's original connect date).
  - Migration: one nullable `Date` column on `account`. Pure DDL, no backfill.

## Context changes

- `context/plaid-integration.md` — add a short bullet under the auth-flow
  section: update mode (account selection) is used for "add more accounts at
  an already-linked bank"; `access_token` unchanged, no `public_token`, new
  accounts surface through the normal `/transactions/sync` loop. Note the
  per-account `import_cutoff` and that the Item-level `import_cutoff` still
  governs the accounts present at first link.

## Constraints

- **Update-mode link_token: no `products`.** Plaid rejects a link_token
  create that passes both `access_token` and `products` for this use case
  (verified against Plaid docs, 2026-08-28). Pass `access_token` +
  `update.account_selection_enabled=true` only.
- **No token exchange on the way back.** `access_token` does not change in
  update mode; `onSuccess` fires with no usable `public_token`. The frontend's
  post-success step is a plain `/api/plaid/sync`, not `/api/plaid/connect`.
- **IDOR guard by direct column comparison** (`item.user_id != user.id` →
  `403`), matching `remove_item` and `context/security-requirements.md`. Do
  not trust a relationship join.
- **Demo user is fully blocked** on the new route (`_load_non_demo_user()` →
  `403`), same as every other write route in `plaid_api.py`.
- **Sanitized Plaid errors only** — the new route reuses the broad
  `try/except → 502 _GENERIC_PLAID_ERROR` pattern from `create_link_token`
  (covers both `ApiException` and raw network errors).
- **Per-account cutoff is additive and NULL-safe.** `NULL` ==
  fall back to the Item cutoff == current behaviour. Accounts present at first
  link are unaffected whether or not they get a stamped value, because
  `date.today()` at first sync already equals the Item's connect-date cutoff.
- **Frontend: extract a shared hook, do not render `ConnectBankButton` per
  row.** `ConnectBankButton` owns a single `usePlaidLink` + OAuth-resume dance
  in the page header. Pull that into a shared hook
  (`usePlaidConnect({ mode: 'new' | { updateItemId } })`); `AccountsPage`
  holds `updatingItemId`, the row buttons set it, one Link driver runs. The
  parked-token localStorage payload carries a discriminator so the OAuth
  return render calls `connectPlaid` (new) or just sync (update). See Grill.
- **Frontend is out of the backend test contract**, per `spec/plaid-connect.md`
  Notes. It is covered by the Playwright e2e (`plaid-institutions.spec.ts`,
  assert the per-institution "Add accounts" control is present — a full Link
  run can't complete under placeholder Sandbox creds) and manual verification
  against the running app.

## Non-Goals

- No standard (non-account-selection) update mode for credential repair /
  `ITEM_LOGIN_REQUIRED` re-auth. Same endpoint could grow a flag later; not
  this change.
- No removing/de-authorizing individual accounts from the UI (update mode can
  deselect, but the local `Account` reconciliation for a removed account is
  out of scope — the sync loop does not currently prune accounts Plaid stops
  returning).
- No per-account sync cursor. The cursor stays Item-scoped
  (`context/plaid-integration.md`); only the import cutoff becomes
  per-account.
- No `/transactions/refresh` call after `onSuccess`. The user's normal sync
  (auto-triggered by the frontend after the flow) picks up the new accounts;
  recurring-stream immediacy is not a feature here.
- No backfill migration for `Account.import_cutoff`.

## Build skills

- `frontend-build` — the `client.ts` helper, the `AccountsPage` per-institution
  control, and the `ConnectBankButton` update-mode + OAuth-resume path.

## First slice

- `spec/plaid-connect.md` (`update-link-token` route) — entry point. Fewest
  dependencies, unblocks the frontend, and is independently testable against
  Sandbox (needs a real linked Item's `access_token`, offline tests stub
  `_plaid_client`). The per-account-cutoff slice in `spec/plaid-sync.md` is
  only reachable once update mode can add accounts to an existing Item, so it
  builds second.

## Grill

Read for this grill: all `context/`, `spec/plaid-connect.md`, `spec/plaid-sync.md`,
`plaid_api.py`, `models.py`, `tests/test_plaid_connect.py`, frontend
`ConnectBankButton.tsx` / `AccountsPage.tsx`. Plaid update-mode + sync behaviour
verified against Plaid docs (see Sources).

### Tension: `date.today()` stamp is wrong for the "connect, then sync later" path
**Challenge:** The plan stamps `Account.import_cutoff = date.today()` on every
new account row. For a first-time connect that normally equals the Item's
connect-date cutoff — *unless* the first sync is retried days later (connect
succeeded, sync failed / user walked away). Then first-link accounts get
stamped with the retry date and silently lose the intended few days of
history that the Item-level cutoff would have imported. That is a behaviour
change to an existing, tested path, not just an addition.
**Resolution:** Only stamp `date.today()` when the account is genuinely new to
an **already-established** Item — gate on `item.last_synced_at is not None`
(equivalently: the Item has synced before, so any account appearing now was
added after first link). Accounts created during the Item's first-ever sync
keep `NULL` → fall back to `_import_cutoff(item)` → identical to today's
behaviour, retry-safe. This makes slice 2 provably inert for every existing
`spec/plaid-sync.md` test case.
**Write-back:** plan Spec-changes bullet for `spec/plaid-sync.md` updated —
stamp condition is `is_new and item.last_synced_at is not None`.

### Tension: `_should_import` is called before the account is resolved
**Challenge:** Both sync loops call `_should_import(plaid_transaction, item)`
*then* `_account_for(...)`. A per-account cutoff needs the `Account` first, and
`_account_for` can return `None` (account not in the page's `accounts` array
and not in the DB). Passing `None` into a per-account gate, or into the
existing `_upsert_transaction`, is undefined.
**Resolution:** Resolve `_account_for(...)` first in both loops; if it returns
`None`, `continue` (skip — matches the fact that `_upsert_transaction(None,…)`
would already crash today, so `added`/`modified` for an unknown account is not
a real case). `_should_import` takes the resolved `Account`; effective cutoff
is `account.import_cutoff or _import_cutoff(item)`.
**Write-back:** plan Open Question on signature churn replaced by this
resolution; test-planning to add one contract line: "an `added` entry for an
`account_id` absent from the page's `accounts` array is skipped, not an
error."

### Tension: three overlapping Link entry points on the Accounts page
**Challenge:** After this change the page has "Connect a bank" (no items),
"Connect another bank" (new institution — and, if the user picks a bank they
already linked, Plaid returns the same `item_id` and `/connect` re-links in
place), and per-institution "Add accounts" (update mode). The middle one
already *partly* does what "Add accounts" does.
**Resolution:** Keep all three; they are distinct intents. "Add accounts" is
scoped to one known Item, skips full bank re-auth where the institution
allows, and is discoverable ("add an account to *this* bank"). Documented as
an enhancement over the full-relink side effect, not a duplicate. Frontend
copy/placement is a `ui-ux-design` detail for build, noted as a non-goal to
resolve here.
**Write-back:** plan Refutation section (below) records the relationship.

### Tension: "reuse ConnectBankButton" vs per-row rendering
**Challenge:** `ConnectBankButton` is rendered once in the page header and
owns a single `usePlaidLink` instance plus the OAuth-resume dance. Per-institution
"Add accounts" buttons live in the list. Reusing the component literally means
either N hook instances or awkward prop-drilling.
**Resolution:** Extract the Link plumbing into a shared hook
(`usePlaidConnect({ mode: 'new' | { updateItemId } })`). `AccountsPage` holds
`updatingItemId` state; the row buttons set it; one Link driver runs. The
parked-token `localStorage` payload gains a discriminator so the OAuth return
render knows whether to call `connectPlaid` (new) or just sync (update).
**Write-back:** plan Constraints — "reuse ConnectBankButton" softened to
"extract a shared hook; do not render ConnectBankButton per row."

### Terminology: "connection" / "account" / "Item"
**Collision:** The original request said "add connections from the already
connected bank." `context/plaid-integration.md` uses **Item** (Plaid's linked
institution) and this app's schema uses **Account** for the thing being added.
"Connection" is not a term in `context/` or `spec/`.
**Resolution:** "Add accounts" is the user-facing verb; the thing added is an
`Account` under an existing `PlaidItem`. No new term enters the specs. Plan
already uses "account" / "Item" throughout.
**Write-back:** none needed — no `context/` term change.

### Prior-decision conflict: `spec/plaid-connect.md` "reconnecting replaces"
**Challenge:** That spec's done-criteria say a second Link flow *replaces* the
stored connection (in-place token update, keep cursor + accounts). The new
route deliberately does neither — it mints a token that leaves the
`access_token` untouched and adds accounts.
**Resolution:** No conflict — additive. Update mode is a third, named mode
alongside first-link and re-link; it is the only one that does not go through
`/item/public_token/exchange`. The spec modification adds a route section, it
does not touch the re-link done-criteria.
**Write-back:** plan Spec-changes bullet already scopes the `plaid-connect.md`
edit to "new route section only."

### Refutation: just skip slice 2 / just use "Connect another bank"
**Argument (strongest against):** (a) The full-relink path already exists: pick
the same bank in "Connect another bank", Plaid returns the same `item_id`,
`/connect` updates in place, next sync ingests any newly-authorized accounts —
so slice 1 is sugar. (b) Slice 2 (per-account cutoff) is a schema + migration
+ four-function change to avoid a one-time history dump the user could just
delete.
**Resolution — (a) holds partially, does not sink slice 1:** the full-relink
path forces complete bank re-authentication even on a healthy Item, is not
discoverable as "add an account to Chase," and depends on an undocumented
side effect. Plaid documents update mode + `account_selection_enabled` as *the*
mechanism for this exact need. Slice 1 stays.
**Resolution — (b) overridden by explicit user decision:** the user was shown
"accept the Item's original cutoff" and chose "cutoff = today for new
accounts." Confirmed (Sources): a newly-added account's history *does* arrive
through `/transactions/sync` as `added` entries on the existing cursor, so
without slice 2 a later-added account dumps up to ~90 days into the budget and
Ready-to-Assign. The nullable-column + `last_synced_at`-gated stamp keeps the
change inert for every existing path, which is the cheapest correct design.
Slice 2 stays.

### Operator prerequisite surfaced by the grill
**Finding:** `update.account_selection_enabled=true` relies on Account Select
v2 being enabled for the Plaid client (Dashboard → Link customization).
Newer clients have it by default; older ones must enable it. Same class of
operator step as registering `PLAID_REDIRECT_URI`.
**Write-back:** added to Open Questions for the operator to confirm before
production use; not a code concern.

## Sources
- Plaid — Link update mode (account selection, no `products`, no token
  exchange, selected accounts in `onSuccess`):
  https://plaid.com/docs/link/update-mode/
- Plaid — Transactions sync migration (a newly-onboarded/added account's
  history returns as `added` through the cursor):
  https://plaid.com/docs/transactions/sync-migration/

## Open Questions

- **Sandbox coverage for the happy path.** A `200` from the new route needs a
  real `/link/token/create` call with a valid `access_token`, i.e. a real
  linked Sandbox Item first (`sandbox_public_token_create` → `/connect`, then
  hit the new route). Confirm in test-planning whether that chains cleanly in
  one test or the happy path is `@requires_plaid_sandbox` like
  `test_link_token_created_for_authenticated_user`, with 401/403/404/502
  covered offline via the stub client.
- **Account Select v2 dashboard toggle.** Operator to confirm it is enabled
  for the production Plaid client before relying on `account_selection_enabled`
  (Sandbox has it on by default). Runbook note, not code.
- **Frontend Link driver shape.** Shared-hook extraction vs generalizing
  `ConnectBankButton` — resolved in principle (shared hook), exact structure
  is a `frontend-build` / `ui-ux-design` call during build.

## Test planning result (2026-08-28)

### Spec files modified
- `spec/plaid-connect.md` — added `### POST /api/plaid/items/<id>/update-link-token`
  contract + 5 error cases (401, 403 demo, 404, 403 not-owner, 502 sanitized).
  `## Tests` + `## Changes` updated with `changes/023` placeholders.
- `spec/plaid-sync.md` — added `#### Per-account import cutoff (changes/023)`
  subsection: `Account.import_cutoff` schema, effective-cutoff rule,
  `last_synced_at`-gated stamp, `_account_for`-first gating, Starting-Balance
  date change, and 5 offline test cases (all user-validated). `## Tests` +
  `## Changes` updated.

### Spec files created
- none (both modified in place).

### Mock boundaries
- Real: Postgres, sync/upsert logic, `_plaid_client` adapter internals.
- Stubbed `_plaid_client` (offline): `update-link-token` success shape +
  401/403/404/403-not-owner/502; every `plaid-sync` per-account-cutoff case
  (mocked `transactions_sync`, seeded `PlaidItem` + `Account`).
- Real Plaid Sandbox (`@requires_plaid_sandbox`): one `update-link-token`
  chain — `sandbox_public_token_create` → `/connect` → new route → `200`.
- No `context/testing.md` change — this reuses the already-recorded Plaid
  Sandbox / offline-stub boundary.

### Context updates
- `context/plaid-integration.md` — pending in build: add the update-mode
  bullet (per plan's "Context changes").

### Test infrastructure notes
- `tests/test_plaid_sync.py` `_mock_sync_response` needs an `accounts`
  argument (currently hardcodes `[]`) so a mocked page can introduce a new
  account. test-writer adds it.
- New nullable `Account.import_cutoff` column → one Alembic migration
  (pure DDL, no backfill), authored in build.

### First slice for test-writer
- `spec/plaid-connect.md` § update-link-token route.
