# Plaid integration

Supersedes `context/simplefin-integration.md` — SimpleFIN replaced by Plaid,
decided 2026-08-26 (see `changes/004-plaid-and-self-host/grill-findings.md`
for the full interrogation). Not yet implemented; re-verify details below
against current Plaid docs before implementing, same discipline that caught
the previous provider's doc drift.

- **Auth flow**: Plaid Link (Plaid's hosted JS/React widget) runs in the
  browser and talks to Plaid directly, returning a short-lived
  `public_token` to the frontend. The frontend sends that to our backend,
  which exchanges it server-to-server via `/item/public_token/exchange` for
  a permanent `access_token` + `item_id`. The app never sees bank login
  credentials, same guarantee as SimpleFIN.
- **OAuth institutions** (Chase, BofA, etc.) redirect the user's *browser*
  back to the app mid-Link-flow — not a Plaid-server-to-app call. Works
  fine on a private (no Funnel) Tailscale deployment as long as the user is
  on a Tailscale-joined device when linking.
- **Data access**: `/transactions/sync` — cursor-based, pure polling, no
  webhook required. Our server calls it on its own schedule/on-demand.
  Webhooks (`SYNC_UPDATES_AVAILABLE`) exist for push-driven updates instead
  of polling, but are explicitly NOT used here — see "Self-hosting" below.
  **Correction (2026-08-26, verified during `plaid-sync.md` planning):**
  this is NOT the same shape as SimpleFIN's `start-date`/`end-date`
  windowing. There's no date range at all — first call omits `cursor`
  and gets the full history (90-day default window); every call after
  passes the previous response's `next_cursor` and gets only what
  changed. No 5-day-overlap heuristic needed; the cursor model is
  idempotent and complete by construction. Response has `added`,
  `modified`, **and `removed`** arrays — `removed` is Plaid's own
  explicit signal (`transaction_id` + `account_id`) that a transaction
  is genuinely gone, not an absence-from-a-window ambiguity. This is a
  materially different (and simpler) mechanism than what
  `simplefin-sync.md` was designed around — see
  `changes/004-plaid-and-self-host/plan.md`'s Grill for what this changes.
- **Rate limits are NOT SimpleFIN's shape either.** Verified: Production
  `/transactions/sync` is limited to 50 requests/minute per Item, 2,500/min
  per client — not a 24/day cap. For a single-user, on-demand/polling app
  this is essentially unreachable under normal use. The client-side
  rate-limiter design (rolling-window counter on `User`) planned for
  SimpleFIN is not needed for Plaid at all — dropped, not carried over.
- **Cardinality**: one `access_token`/`item_id` per linked institution
  (Plaid's "Item"). We're keeping single-institution-per-user, matching the
  current SimpleFIN-era scope (`context/mvp-scope.md` never called for
  multi-bank) — one Item per `User`, same shape as today's single-column
  design, just renamed.
- **Storage**: `User.plaid_access_token_encrypted` (replaces
  `simplefin_access_url_encrypted`), `User.plaid_item_id` (new — Plaid
  splits identity from secret where SimpleFIN embedded both in one URL).
  Same Fernet-at-rest pattern as before; same security requirement basis
  (Plaid, like SimpleFIN, requires strong protection of the access
  credential).
- **Sync cursor scope, verified during `plaid-sync.md` planning**: the
  `cursor`/`next_cursor` in `/transactions/sync` is scoped to the Item by
  default — one cursor covers every account under it. It only becomes
  per-account if requests filter by `account_id` ("specifying an
  `account_id` effectively creates a separate incremental update stream —
  and therefore a separate cursor — for that account," per Plaid's docs).
  This project never filters by `account_id`, so the cursor lives on
  `User.plaid_sync_cursor`, not `Account`. An earlier planning pass
  guessed `Account`-level without checking this — corrected here.
- **No response-size defense needed for `/transactions/sync` either**,
  same reasoning as `/link/token/create` and `/item/public_token/exchange`
  (see "Storage" above and `spec/plaid-connect.md`'s Notes): every Plaid
  SDK call goes to a fixed, environment-selected, trusted host, never a
  client-supplied URL. The unbounded-response-body defense SimpleFIN
  needed doesn't transfer — an earlier planning pass proposed carrying it
  forward "just in case" without re-examining whether the same trust
  reasoning already established for `plaid-connect.md` also covered this
  call. It does.
- **Field naming**: `plaid_account_id`, `plaid_transaction_id` replace the
  `simplefin_*` equivalents on `Account`/`Transaction`. Single-provider app
  — no provider-neutral abstraction, per the grill's terminology resolution.
- **Environments**: Sandbox (free, fake data) → Development/Production.
  Plaid offers a free Trial plan (as of 2026-04-15) for new teams with real
  production data, capped at 10 Production Items — comfortably covers a
  single-user personal app. Re-verify current pricing before going to
  production; Plaid's pricing page is the source of truth, not this note.
- **Pricing model**: per-connected-account, either one-time or subscription
  depending on product — exact figures not publicly listed for all tiers as
  of this research pass (2026-08-26). Confirm actual cost before linking a
  real account.

## Self-hosting implication (why polling, not webhooks)
Webhooks require Plaid's servers to reach ours — on Tailscale that means
Funnel, i.e. real public HTTPS ingress via Tailscale's relay, not a
private-only tailnet. Decided against this (see grill) to keep the
self-hosted deployment fully private. Consequence: sync is polling-only —
but see the correction below on which specific mechanics do and don't
carry over from the original SimpleFIN sync design; less of it survived
unchanged than first assumed here.

**Correction (2026-08-26, during `plaid-sync.md` planning):** this
section originally claimed "upsert semantics, no-delete-on-absence,
rate/window tracking all carry over conceptually." Verified against real
docs while writing that slice's contract — only the upsert-and-never-
touch-`category_id` principle actually survives unchanged. The other two
don't: `removed` is an explicit, authoritative deletion signal (delete on
it, the opposite of "no-delete-on-absence," which was reasoned around
SimpleFIN's *windowed* absence specifically); and rate/window tracking
isn't needed at all, Plaid's real limits (50 req/min per Item) aren't in
the same universe as SimpleFIN's 24/day cap. "Polling-only" is the one
architectural property that's actually the same — the sync *mechanics*
underneath are meaningfully different, not a drop-in port.
