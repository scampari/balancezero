# Open Questions: Plaid connect/sync + self-hosted deploy

> Last updated: 2026-08-26

No blocking questions. Everything below is an assumption with a low-cost
correction path — none require rework beyond a column/constant/response-key
change if wrong.

## Assumptions (agent proceeding unless corrected)

### Cursor storage granularity
- **Status:** assumption-accepted
- **Confidence:** medium
- **Slices affected:** `plaid-sync.md`
- **What I'm assuming:** `Account.plaid_sync_cursor` (per-account), not a
  single cursor on `User`/Item.
- **Rationale:** Plaid's `removed` array entries carry `account_id`
  alongside `transaction_id`, which reads as account-relevant, but Plaid's
  docs describe the cursor as tracking the Item as a whole. Genuinely
  ambiguous from documentation alone.
- **If wrong, impact:** Move the column from `Account` to `User`
  (single-institution scope means there's exactly one of either right now)
  — a one-column migration change, not a structural rework.
- **Correction:** _(filled by human if wrong)_
- **Resolution:** _(filled once test-planning verifies against real Plaid
  Sandbox behavior)_

### Sync response shape
- **Status:** assumption-accepted
- **Confidence:** medium
- **Slices affected:** `plaid-sync.md`
- **What I'm assuming:** Structured counts —
  `{"accounts_synced": N, "transactions_added": X, "transactions_modified":
  Y, "transactions_removed": Z}` — exact keys TBD.
- **Rationale:** Matches this codebase's established pattern (see
  `changes/003-simplefin-sync/open-questions.md`'s equivalent item, same
  reasoning carries over unchanged).
- **If wrong, impact:** Response-shape-only change; nothing downstream
  consumes it yet.
- **Correction:** _(filled by human if wrong)_
- **Resolution:** _(filled once test-planning locks it)_

### Response body size cap
- **Status:** assumption-accepted
- **Confidence:** medium
- **Slices affected:** `plaid-sync.md`
- **What I'm assuming:** Bounded streamed read, low-single-digit-MB range —
  unchanged reasoning from the SimpleFIN-era version of this same question.
- **Rationale:** Carries forward the `/connect` security review's
  unbounded-response-body finding proactively.
- **If wrong, impact:** Constant tweak.
- **Correction:** _(filled by human if wrong)_
- **Resolution:** _(filled once test-planning locks it)_

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
