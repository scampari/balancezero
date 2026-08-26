# Open Questions: Plaid connect/sync + self-hosted deploy

> Last updated: 2026-08-26

No blocking questions. Everything below is an assumption with a low-cost
correction path — none require rework beyond a column/constant/response-key
change if wrong.

## Assumptions (agent proceeding unless corrected)

### ~~Cursor storage granularity~~ — RESOLVED, removed from open questions
- **Status:** resolved (was assumption-accepted, medium confidence)
- **Resolved by:** auto-test-planning, 2026-08-26, verified against current
  Plaid docs. The cursor is Item-scoped by default (one cursor for every
  account under the Item); it only becomes per-account if requests filter
  by `account_id`, which this project's contract doesn't do. Lives on
  `User.plaid_sync_cursor`, not `Account`. The plan's original
  `Account`-level guess was wrong — corrected in `spec/plaid-sync.md` and
  `context/plaid-integration.md`.

### ~~Sync response shape~~ — RESOLVED, removed from open questions
- **Status:** resolved (was assumption-accepted, medium confidence)
- **Resolved by:** auto-test-planning, 2026-08-26 — locked as
  `{"accounts_synced": N, "transactions_added": X, "transactions_modified":
  Y, "transactions_removed": Z}` in `spec/plaid-sync.md`'s integration test
  contract. Matches this codebase's established pattern of returning
  meaningful shape rather than a bare status string.

### ~~Response body size cap~~ — RESOLVED (not needed), removed from open questions
- **Status:** resolved (was assumption-accepted, medium confidence) —
  resolution differs from the original assumption
- **Resolved by:** auto-test-planning, 2026-08-26. The original assumption
  carried forward `/connect`'s unbounded-response-body defense "just in
  case," without re-examining whether the trust-boundary reasoning that
  already exempted `plaid-connect.md` from SimpleFIN's SSRF/redirect
  defenses also exempted this call from the size-cap defense specifically.
  It does: `/transactions/sync` goes through the same official SDK against
  the same fixed, trusted, environment-selected Plaid host, never a
  client-supplied URL. No size cap needed. See
  `context/plaid-integration.md` and `spec/plaid-connect.md`'s Notes for
  the underlying reasoning this reuses.

### Single-hostname, same-origin production topology
- **Status:** assumption-accepted
- **Confidence:** medium
- **Slices affected:** `self-hosted-deploy.md`
- **What I'm assuming:** Production serves frontend + API under one
  Tailscale MagicDNS hostname (Ingress path-routes `/api/*` vs. `/*`),
  collapsing today's two-origin dev CORS setup into same-origin for prod
  only. Dev (`dev.sh`, two servers) stays unchanged.
- **Rationale:** Simpler and more secure — `SameSite=Strict` refresh-token
  cookie behaves exactly as intended same-origin, no cross-origin
  credentialed-request edge cases to reason about in production.
- **If wrong, impact:** Real but contained — would mean keeping two
  Services/hostnames in prod and keeping CORS configured there too. Doesn't
  cascade into `plaid-connect.md`/`plaid-sync.md`'s contracts.
- **Correction:** _(filled by human if wrong)_
- **Resolution:** _(filled once test-planning/build locks the Ingress
  design)_

### ~~Sandbox OAuth-institution coverage~~ — RESOLVED, removed from open questions
- **Status:** resolved (was assumption-accepted, medium confidence)
- **Resolved by:** auto-test-planning, 2026-08-26, verified against current
  Plaid docs (not general knowledge this time). Plaid Sandbox uses "a
  single generic OAuth flow rather than institution-specific OAuth
  behavior," and accepts `http://localhost` redirect URIs in Sandbox
  (Production requires `https`). `plaid-connect.md` does NOT need
  `self-hosted-deploy.md`'s real hostname to exist first — confirmed, not
  just assumed. Confidence raised to high. See `spec/plaid-connect.md`'s
  Notes for the full resolution.

### ~~No data migration for existing local SimpleFIN connection~~ — RESOLVED, removed from open questions
- **Status:** resolved (was assumption-accepted, medium confidence)
- **Resolved by:** direct verification, 2026-08-26 — queried the local
  `dev-db` directly (`docker compose up -d dev-db`, then a `SELECT` against
  the `user` table). Only one user row exists: the seeded demo user
  (`is_demo=true`), which correctly has no SimpleFIN connection. Sam's real
  user account was never created locally, so the real Setup Token
  `changes/002/plan.md` mentioned was apparently never entered into the
  running app (or was tried against a since-reset database). There is
  nothing for this migration to discard — confirmed, not assumed.
