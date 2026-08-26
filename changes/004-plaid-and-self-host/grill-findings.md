# Grill: Plaid + self-hosted (Tailscale) pivot

> Date: 2026-08-26
> Interrogated a proposal, not yet a written plan: replace SimpleFIN with
> Plaid (full replacement); replace the AWS EKS deploy target with
> self-hosting over Tailscale (full replacement). Both confirmed full
> replacements by the user before this grill ran.

## Tension: Backend reachability during Plaid Link's OAuth redirect
**Challenge:** Plaid "OAuth institutions" (Chase, BofA, etc.) redirect the
user's browser back to the app mid-flow. Does a Tailscale-private (no
Funnel) deployment break this?
**Resolution:** No break — the redirect target is the user's own browser,
not a Plaid-server-to-app call. Works on a private tailnet as long as the
user is on a Tailscale-joined device when linking, which matches the
personal-use intent anyway.
**Write-back:** `context/plaid-integration.md` (new).

## Tension: Push webhooks vs. pure polling
**Challenge:** Plaid supports both `SYNC_UPDATES_AVAILABLE` webhook push and
standalone polling via `/transactions/sync`. Webhooks require Plaid's
servers to reach the app — on Tailscale that means Funnel (real public
HTTPS ingress via Tailscale's relay), not a private-only tailnet. "Self-host
via Tailscale" and "webhook-driven sync" are in tension.
**Resolution:** Polling only. No Funnel, no public ingress at all — matches
"self-host, private network" literally. `/transactions/sync` works
standalone; the server polls on a schedule/on-demand. This is architecturally
the same shape as the already-designed SimpleFIN sync slice (upsert,
rate/window tracking, no-delete-on-absence) — most of that design carries
over to Plaid with different field names, not a from-scratch redesign.
**Write-back:** `context/plaid-integration.md` (new), `context/tech-stack.md`.

## Prior-decision conflict: EKS's stated purpose (Kubernetes portfolio value)
**Challenge:** `context/tech-stack.md` recorded EKS as chosen "specifically
to demonstrate Kubernetes skills as part of this portfolio project" — a
deliberate reason, not just a default. A plain self-hosted box (e.g. Docker
Compose) drops that reason without replacing it.
**Resolution:** Self-host a lightweight k3s cluster instead of a plain
Compose box. Keeps a real Kubernetes deployment target for the portfolio,
reachable only over Tailscale (no public ingress, consistent with the
polling-only resolution above), while dropping AWS cost/complexity.
**Write-back:** `context/tech-stack.md` — superseded EKS entry.

## Tension: Plaid Item/access_token cardinality vs. existing single-column model
**Challenge:** Plaid's Item model supports multiple linked institutions per
user (each Item its own `access_token`/`item_id`). The current schema has
one SimpleFIN connection column on `User` — a 1:1 assumption. Does Plaid
need a new 1:many table, or does the existing shape still fit?
**Resolution:** Single institution per user, same as today.
`context/mvp-scope.md` never called for multi-bank, and it's not being
added now — just rename the existing column
(`simplefin_access_url_encrypted` → `plaid_access_token_encrypted`, plus
a new `plaid_item_id` column) rather than introducing an Item table for a
capability nobody asked for.
**Write-back:** `context/plaid-integration.md` (new) — explicitly notes
single-institution is a scope choice, not a technical ceiling, so it's
easy to find if this changes later.

## Terminology: SimpleFIN-specific naming throughout
**Challenge:** `models.py` and `context/simplefin-integration.md` use
`simplefin_access_url_encrypted`, `simplefin_account_id`,
`simplefin_transaction_id`. Plaid's shape is `access_token` + `item_id`,
not an embedded-credential URL — same concept, different structure.
**Resolution:** Rename to `plaid_access_token_encrypted`, `plaid_item_id`
(new), `plaid_account_id`, `plaid_transaction_id`. Provider-neutral naming
(e.g. `external_access_token_encrypted`) isn't worth the abstraction cost
for a single-provider app — matches the "full replacement, not
multi-provider" scope decision.
**Write-back:** Flagged for the migration this pivot will need; not written
to context/ itself (it's a spec/implementation detail, not an architectural
decision).

## Refutation: sunk cost in the already-built SimpleFIN work
**Argument:** `spec/simplefin-connect.md` is built, tested (15 green tests),
and already survived one security review. Replacing it discards real,
working effort — the strongest case against this pivot.
**Resolution:** Doesn't hold. Checked git history: EKS was never built,
only decided (`context/tech-stack.md`, `context/mvp-scope.md`: "Not yet
started: ... EKS deploy") — so the deploy-target half of this pivot costs
nothing in rework, only a context/ update. The provider half does have
real sunk cost, but the user directly weighed that against the cheaper
alternative (keep SimpleFIN, add Plaid alongside) before choosing full
replacement anyway — the refutation doesn't surface anything not already
in view when that choice was made.

## Sequencing decision
Both changes are being planned together as one change (`004-plaid-and-self-host`),
not staged — the user confirmed they don't block each other technically and
both are already decided, so there's no risk-reduction benefit to splitting
them.

## Superseded artifacts (not yet executed — pending plan)
- `spec/simplefin-connect.md` — to be marked superseded once
  `spec/plaid-connect.md` exists.
- `spec/simplefin-sync.md` — to be marked superseded once
  `spec/plaid-sync.md` exists (was only ever a stub, never built).
- `changes/003-simplefin-sync/` (draft PR #1) — to be closed once this
  change's plan is confirmed; not touched by this grill pass since closing
  a PR is a visible action outside this skill's scope.
