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
self-hosted deployment fully private. Consequence: sync is polling-only,
same operational shape as the SimpleFIN sync design that was already
planned (upsert semantics, no-delete-on-absence, rate/window tracking all
carry over conceptually) — this is not a from-scratch redesign of the sync
approach, just a different upstream API.
