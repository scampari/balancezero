# Plan: Plaid connect/sync + self-hosted k3s-over-Tailscale deploy

> Date: 2026-08-26
> Status: planning
> Branch: agent/plaid-and-self-host
> PR: TBD

## What & Why
Replaces SimpleFIN with Plaid as the bank-data provider, and replaces the
never-built AWS EKS deploy target with a self-hosted k3s cluster reachable
only over Tailscale. Both are full replacements, decided and grilled at the
architecture level in this same change directory's `grill-findings.md`
before any spec existed. This plan turns those resolutions into actual spec
changes: `spec/plaid-connect.md`, `spec/plaid-sync.md`,
`spec/self-hosted-deploy.md`, superseding `spec/simplefin-connect.md` and
`spec/simplefin-sync.md`.

Building the plan surfaced two more facts that change resolutions already
recorded in `grill-findings.md` — see this plan's own Grill section,
"Corrections to the architecture-level grill," rather than silently
overriding them.

## Spec changes
- `spec/plaid-connect.md` (new) — Plaid Link token creation + public_token→
  access_token/item_id exchange, encrypted storage, single-institution.
- `spec/plaid-sync.md` (new) — cursor-based polling sync via
  `/transactions/sync`, upsert + explicit-removal deletion.
- `spec/self-hosted-deploy.md` (new) — k3s cluster, Tailscale Kubernetes
  Operator (L7 Ingress), Postgres via PVC, secrets-at-rest.
- `spec/simplefin-connect.md` (superseded by `spec/plaid-connect.md`)
- `spec/simplefin-sync.md` (superseded by `spec/plaid-sync.md`) — was only
  ever a stub, never built.
- `spec/README.md` — index updated to reflect the above.

## Slice order
- `spec/plaid-connect.md` — first (entry point). Depends on: `auth.md`
  (built). Sandbox/non-OAuth-institution testing has no dependency on
  `self-hosted-deploy.md`; real OAuth-institution linking does (needs a
  stable hostname for the redirect URI) — see Grill, "OAuth redirect URI
  needs a real hostname."
- `spec/plaid-sync.md` — depends on: `plaid-connect.md`.
- `spec/self-hosted-deploy.md` — depends on: `frontend-app.md`,
  `budget-api.md` (built) — packages the existing app; not blocked by
  Plaid work, can be built in parallel with `plaid-connect.md`/
  `plaid-sync.md`.

## Context changes
- `context/plaid-integration.md` — corrected during this plan (cursor
  model, not date-windowing; real rate limits, not SimpleFIN's shape) — see
  `research-plan.md`.
- `context/tech-stack.md` — will get a "self-hosted-deploy built" note once
  that slice ships; no change needed at plan time, already updated by the
  architecture-level grill.

## Constraints

### plaid-connect.md
- **Two backend endpoints, not one** — `POST /api/plaid/link-token`
  (creates a `link_token`, the config step Plaid requires *before* showing
  Link to the user) and `POST /api/plaid/connect` (exchanges the resulting
  `public_token` for `access_token`/`item_id` *after* the user completes
  Link). SimpleFIN's flow only needed the second half (paste a token,
  exchange it) — Plaid's Link widget needs a token minted first. confidence:
  high (directly from Plaid's documented flow).
- **`GET /api/plaid/status`** — same shape as SimpleFIN's (`{"connected":
  bool}`), same demo-user guard (`403`), same "reconnect replaces" semantics
  (`200`, not `409`, per `simplefin-connect.md`'s established pattern).
  confidence: high.
- **Storage**: `User.plaid_access_token_encrypted` (Fernet, LargeBinary —
  same pattern as before) + `User.plaid_item_id` (new, plaintext — Plaid's
  own docs treat `item_id` as an identifier, not a secret; only
  `access_token` needs encryption). confidence: high.
- **Migration renames, doesn't just adds**: `simplefin_access_url_encrypted`
  → `plaid_access_token_encrypted`, `Account.simplefin_account_id` →
  `plaid_account_id`, `Transaction.simplefin_transaction_id` →
  `plaid_transaction_id`, plus new `User.plaid_item_id`. Also adds the
  `UniqueConstraint("user_id", "plaid_account_id")` on `Account` that was
  already flagged as missing for SimpleFIN and never built — same gap,
  same fix, just under the new name. confidence: high.
- **Encryption key env var renamed**: `SIMPLEFIN_ENCRYPTION_KEY` →
  `PLAID_ENCRYPTION_KEY`, plus two new required vars, `PLAID_CLIENT_ID` and
  `PLAID_SECRET` (Plaid's own API credentials — a concept SimpleFIN didn't
  have; SimpleFIN required no API key of our own, just the user's Setup
  Token). No default/fallback, same "fail loudly" discipline as before.
  confidence: high.

### plaid-sync.md
- **`POST /api/plaid/sync`** — on-demand, not scheduled (still true, see
  `grill-findings.md`). confidence: high.
- **Cursor storage**: new column, `Account.plaid_sync_cursor` (nullable —
  null means "never synced," triggers the initial full-history call).
  Stored per-Item (i.e., per-user, since single-institution) is also
  possible, but per-Account matches the `removed` array's shape
  (`account_id` + `transaction_id`) better and avoids a partial-sync
  ambiguity if we ever needed to resume mid-Item. confidence: medium
  (ASSUMPTION: per-Account vs. per-Item cursor storage — Plaid's own docs
  describe the cursor as tracking the *Item*, not individual accounts, so
  a `User`- or Item-level column may actually be the more faithful match;
  needs test-planning to confirm against Plaid's actual behavior rather
  than my inference).
- **Upsert semantics carry over from the earlier grill**: never touch
  `Transaction.category_id` on update (still true — Plaid's `modified`
  entries are the same category of risk as SimpleFIN's amount/pending
  corrections). confidence: high.
- **Deletion semantics do NOT carry over unchanged** — see Grill,
  "Correcting the no-delete resolution for Plaid." confidence: high (new
  resolution, well-evidenced).
- **No rate-limit tracking** — dropped entirely, not carried over from the
  SimpleFIN design. confidence: high (Plaid's real limits, 50/min per Item,
  make this dead code for a single-user on-demand app).
- **Response shape**: structured counts, same spirit as the SimpleFIN
  design (`accounts_synced`, `transactions_added`, `transactions_modified`,
  `transactions_removed`) — exact keys still test-planning's call.
  confidence: medium.
- **Response body size cap on the outbound sync call**: still applies
  (same principle as before — this call can return significant transaction
  volume). confidence: medium (principle: high; exact byte cap:
  test-planning's call, unchanged reasoning from the earlier grill).

### self-hosted-deploy.md
- **k3s single-node cluster**, Tailscale Kubernetes Operator installed via
  Helm, authenticated with a tag-scoped Tailscale OAuth client
  (`tag:k8s-operator`). confidence: high (verified against current
  Tailscale docs, see `research-plan.md`).
- **Exposure via L7 Ingress**, not L3 Service — gets automatic HTTPS and a
  stable MagicDNS hostname (`balancezero.<tailnet>.ts.net`). No Funnel
  anywhere in this spec — reaffirms the architecture-level grill's
  polling-only, private-tailnet-only resolution. confidence: high.
- **Single hostname for frontend + API in production**, reverse-proxied by
  the Ingress (`/api/*` → Flask Service, `/*` → static React build served
  from a small nginx/static Service) — collapses the dev-time two-origin
  CORS setup (`ALLOWED_ORIGIN`, cross-origin credentialed cookies) into a
  same-origin deployment. Dev keeps the existing two-server setup
  (`dev.sh`) unchanged; this is a production-only topology change.
  confidence: medium (ASSUMPTION: simpler and more secure — same-origin
  means `SameSite=Strict` behaves exactly as intended with no cross-origin
  edge cases — but it's a real architecture call test-planning should
  confirm, not a given).
- **Postgres via a StatefulSet + PVC**, using k3s's built-in
  `local-path-provisioner` (no extra storage class installation needed).
  confidence: high.
- **Secrets-at-rest**: k3s's datastore does not encrypt secrets by default;
  `--secrets-encryption` must be enabled at cluster install time. Given
  this app stores a real bank-access credential
  (`plaid_access_token_encrypted`, plus the app already encrypts it at the
  DB layer too — defense in depth), this is a real requirement, not
  optional hardening. confidence: high (direct security-requirements.md
  consequence, verified as a real k3s flag, not assumed).
- **OAuth redirect URI needs this spec's hostname** — `plaid-connect.md`'s
  real (non-Sandbox) OAuth-institution linking needs a stable, registered
  redirect URI, which is this spec's MagicDNS hostname. Sandbox/dev testing
  of `plaid-connect.md` doesn't need it (Plaid's Sandbox test institutions
  are typically non-OAuth). confidence: medium (ASSUMPTION: exactly which
  Sandbox institutions require/skip OAuth is Plaid-specific detail
  test-planning should verify directly rather than assume from general
  knowledge).

## Non-Goals
- Multi-institution linking (still out of scope, reaffirmed from the
  architecture-level grill).
- Tailscale Funnel / any public ingress (reaffirmed).
- Multi-node k3s / HA (single-node is enough for single-user personal use;
  nothing here blocks adding nodes later).
- CI/CD automation of the deploy (GitHub Actions → k3s pipeline) — this
  plan covers the cluster/manifests existing and being reachable; wiring
  automated deploys is a separate, later concern, same non-goal pattern
  `changes/002`'s plan used for EKS/CI.
- Migrating any existing local SimpleFIN connection state — see Grill,
  "Real SimpleFIN connection may already exist locally."

## Build skills
- `app-security` — same rationale as before (encrypted credential storage,
  new outbound API surface), plus this change adds a real deploy/secrets
  surface (`--secrets-encryption`, Kubernetes Secrets) that didn't exist
  when EKS was still just a plan.
- `cloud-infrastructure` — Kubernetes manifests, Helm install of the
  Tailscale operator.

## Grill

### Corrections to the architecture-level grill
Two facts surfaced while writing this plan that change resolutions already
recorded in `grill-findings.md`. Recorded here explicitly rather than
silently overriding — the earlier grill's *reasoning* wasn't wrong given
what was known at the time; new evidence changed the answer.

#### Correcting the no-delete resolution for Plaid
- **Status:** resolved (supersedes the equivalent finding in
  `grill-findings.md`, which was about SimpleFIN specifically and remains
  correct for SimpleFIN)
- **Context:** `grill-findings.md` resolved "never delete a local
  Transaction based on absence from a sync response" — reasoned around
  SimpleFIN's `start-date`-windowed responses, where absence could just
  mean "outside the requested window," not real deletion. Plaid's
  `/transactions/sync` has no windowing at all and returns an explicit
  `removed` array (`transaction_id` + `account_id`) — a deliberate signal,
  not an absence inference.
- **Decision:** For Plaid, delete the local `Transaction` when it appears
  in `removed`. Hard delete (`db.session.delete`), matching this
  codebase's existing pattern — no soft-delete precedent anywhere in
  `models.py` (cascade="all, delete-orphan" used throughout).
- **Confidence:** high
- **Consequences:** `spec/plaid-sync.md`'s Done-when needs an explicit
  test: a transaction present in one sync, absent-via-`removed` in the
  next, is gone locally afterward. Its category assignment (if any) is
  lost with it — acceptable, since the transaction itself no longer
  exists at the bank.
- **Alternatives considered:** Soft-delete (rejected — no existing pattern
  to extend, no identified need to retain a record of a genuinely-removed
  transaction).

#### Correcting the rate-limit-tracking carryover
- **Status:** resolved (supersedes `grill-findings.md`'s rate-limit
  finding, which reasoned from SimpleFIN's 24/day cap)
- **Context:** `grill-findings.md` designed a client-side rolling-window
  rate limiter, reasoning it would "carry over conceptually" to Plaid.
  Verified Plaid's actual limits: 50 requests/minute per Item, 2,500/min
  per client — not a daily cap, and effectively unreachable for a
  single-user on-demand app.
- **Decision:** No client-side rate-limit tracking for Plaid. Dropped
  entirely.
- **Confidence:** high
- **Consequences:** `spec/plaid-sync.md` is simpler than
  `spec/simplefin-sync.md` was going to be — one fewer migration column,
  one fewer piece of logic, one fewer thing to test.
- **Alternatives considered:** Keep a lightweight tracker anyway as a
  defensive backstop (rejected — SimpleFIN's version was justified by a
  cheap-insurance argument against a real, easy-to-hit daily cap; Plaid's
  limits aren't in the same universe of riskiness, so the same insurance
  logic doesn't transfer).

### Tensions & Structure

#### Plaid Link needs a token-creation round trip SimpleFIN didn't
- **Status:** resolved
- **Context:** SimpleFIN's connect flow was a single backend call (paste
  token → exchange). Plaid's Link widget requires the backend to create a
  `link_token` *before* the widget can even open.
- **Decision:** Two endpoints in `plaid-connect.md`: `POST
  /api/plaid/link-token` then `POST /api/plaid/connect`. Not a rename of
  one endpoint — a genuinely different shape.
- **Confidence:** high
- **Consequences:** `plaid-connect.md`'s contract has two setup/action
  pairs where `simplefin-connect.md` had one; frontend work (out of scope
  for this plan, but worth flagging) needs the `react-plaid-link` package,
  not present in `frontend/package.json` today.
- **Alternatives considered:** n/a — this is how Plaid's API works, not a
  design choice.

#### Cursor storage granularity (Account vs. Item/User)
- **Status:** assumption
- **Context:** Plaid's cursor conceptually tracks an Item (one per user,
  given single-institution scope), but the `removed` array's entries carry
  `account_id`, suggesting account-level granularity might matter for
  correctness.
- **Decision:** Store the cursor on `Account.plaid_sync_cursor` for now,
  tentatively — flagged in Constraints above as medium confidence
  specifically so test-planning verifies against Plaid's actual behavior
  rather than this plan's inference.
- **Confidence:** medium
- **Consequences:** If test-planning finds the cursor is really Item-scoped
  (not per-account), this becomes a `User`-level column instead — a
  one-column migration change, not a structural rework.
- **Alternatives considered:** `User.plaid_sync_cursor` (rejected only
  tentatively — plausible this is actually more correct, hence the medium
  confidence rather than high).

#### Real SimpleFIN connection may already exist locally
- **Status:** assumption
- **Context:** `changes/002/plan.md` recorded that the user had a real
  SimpleFIN Setup Token ready and intended to enter it directly into the
  running app once `/connect` existed. If that happened, a real (not just
  Sandbox-test) encrypted Access URL may currently sit in a local dev
  database's `simplefin_access_url_encrypted` column.
- **Decision:** The migration renames/drops that column without a data
  migration path — any existing SimpleFIN connection state is discarded,
  not carried into `plaid_access_token_encrypted` (the two providers'
  credentials aren't interchangeable, so there's nothing meaningful to
  migrate). Re-linking via Plaid Link is the expected path. Sync was never
  built, so no transaction history is lost either way.
- **Confidence:** medium (ASSUMPTION: acceptable because this is local/
  personal-use data, not a live production user base — flagging in case
  that assumption is wrong)
- **Consequences:** None to the spec contracts themselves; worth a
  one-line callout in the migration's own description so it isn't a silent
  surprise.
- **Alternatives considered:** A data-preserving migration path (rejected
  — there's no such thing between two structurally different credential
  types; the alternative would just be *not* dropping the old column,
  which contradicts the "full replacement" scope decision already made).

### Terminology

#### "Item" (Plaid) vs. existing vocabulary
- **Status:** resolved
- **Context:** Plaid's own term for a linked institution connection is
  "Item" — a term this codebase doesn't currently use for anything, no
  collision. Worth confirming deliberately rather than silently adopting
  Plaid's vocabulary into our own docs unexamined.
- **Decision:** Use "Item" only when referring to Plaid's own API concept
  (e.g., `item_id`); use "connection" (already established in
  `context/mvp-scope.md`, `spec/simplefin-connect.md`) when referring to
  our own user-facing concept of "this user has linked a bank." They're
  the same thing at single-institution scope, but keeping the words
  separate avoids conflating our UI/API language with Plaid's internal
  terminology if multi-institution ever gets built later.
- **Confidence:** high
- **Consequences:** `spec/plaid-connect.md`'s prose uses "connection" for
  user-facing description, "Item"/`item_id` only for the literal field
  name.
- **Alternatives considered:** Adopt "Item" as the project's own term
  throughout (rejected — needlessly couples our vocabulary to one
  vendor's API naming).

### Prior-Decision Conflicts

#### This plan reaffirms, and in two places corrects, the architecture-level grill
- **Status:** resolved
- **Context:** `grill-findings.md` (architecture level) vs. this plan
  (spec level) — two findings changed (see "Corrections" above), the rest
  stand as originally resolved (polling-only, no Funnel, single-institution,
  k3s-for-portfolio-value, terminology renames).
- **Decision:** Both corrections are recorded explicitly, with the
  evidence that changed them, rather than quietly landing different specs
  than the architecture grill implied.
- **Confidence:** high
- **Consequences:** `context/plaid-integration.md` updated in place (see
  `research-plan.md`) rather than left contradicting this plan.
- **Alternatives considered:** n/a.

### Refutation
- **Strongest argument against this plan:** It's large — 5 specs touched,
  a real data migration, a new deploy target from scratch, and it drops a
  working (if simple) rate-limiter design partway through, suggesting the
  architecture-level grill didn't have enough evidence yet to fully trust
  its own conclusions. Maybe this should have been split: land
  `plaid-connect.md`/`plaid-sync.md` as one change, `self-hosted-deploy.md`
  as a separate one, since they don't actually depend on each other (per
  Slice order above).
- **Resolution:** The user explicitly declined that split when asked
  ("Sequencing" question, architecture-level grill) — both were already
  decided and don't block each other technically, so staging them
  serves risk-reduction the user didn't ask for. The corrections found
  while planning are a sign the process worked (research surfaced real
  facts before they hit locked tests), not a sign the plan is unsound —
  they made the resulting specs *simpler* (one fewer migration column, no
  rate-limit logic), not more complex. Proceeding as one combined plan,
  as decided.

## Open Questions
See `open-questions.md` for full detail.
- 🟡 Cursor storage granularity (Account vs. Item/User column) — affects:
  `plaid-sync.md`
- 🟡 Sync response shape (exact JSON keys) — affects: `plaid-sync.md`
- 🟡 Response body size cap (bytes) — affects: `plaid-sync.md`
- 🟡 Single-hostname same-origin prod topology — affects:
  `self-hosted-deploy.md`
- 🟡 Sandbox OAuth-institution coverage for testing without
  `self-hosted-deploy.md` — affects: `plaid-connect.md`
- 🟡 No data migration for any existing local SimpleFIN connection —
  affects: the migration itself
