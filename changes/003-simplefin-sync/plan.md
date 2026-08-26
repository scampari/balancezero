# Plan: SimpleFIN sync

> Date: 2026-08-26
> Status: planning
> Branch: agent/simplefin-sync
> PR: TBD

## Kickoff note
No kickoff was passed to this invocation. `spec/simplefin-connect.md` shipped
(263a050), and `changes/002-simplefin-and-transactions/plan.md` already named
`spec/simplefin-sync.md` as the third slice of that change — "pulls accounts +
transactions via the stored Access URL, respects the 24-requests/day cap and
90-day max range" — but it was never planned, contracted, or built. Treated
that as the kickoff: the next explicitly-declared, unbuilt MVP item
(`context/mvp-scope.md` item 2).

## What & Why
Lets a connected real user pull their actual account balances and transactions
from SimpleFIN into the app, on demand. This is the last piece that makes the
SimpleFIN connection (built in 002) actually useful — right now a connected
user has an encrypted Access URL and nothing that ever reads it.

## Spec changes
- `spec/simplefin-sync.md` (new) — on-demand sync of accounts + transactions
  for the connected user via the stored Access URL.

## Slice order
- `spec/simplefin-sync.md` — depends on: `simplefin-connect.md` (built). Only
  slice in this change; no other in-scope specs.

## Context changes
- `context/simplefin-integration.md` — added a "Sync details" section
  (agent-proposed, unconfirmed) with verified field names, partial-failure
  shape, graduated rate-limit enforcement, and the 5-day overlap
  recommendation. See `research.md`.

## Constraints
- Trigger is a new authenticated endpoint, `POST /api/simplefin/sync`, added
  to the existing `simplefin_bp` blueprint (same resource area as
  `/connect`/`/status`, same `url_prefix`) — not a scheduled/cron job.
  confidence: high (explicit non-goal in `changes/002/plan.md`: "wiring it to
  run automatically on a schedule is a follow-up once the manual path is
  proven").
- Demo user guard: `403` on sync, same `is_demo` check as `/connect`.
  confidence: high (established pattern, same file).
- Not-yet-connected user (`simplefin_access_url_encrypted is None`) calling
  `/sync` gets `409` — a precondition/state failure, not a `400` (input is
  fine, account state is wrong) or `403` (not an ownership issue).
  confidence: medium (ASSUMPTION: no existing precedent for this exact
  situation in the codebase to confirm against).
- **Account upsert requires a new migration**: add
  `UniqueConstraint("user_id", "simplefin_account_id")` on `Account`. Today
  there is no DB-level constraint enforcing one `Account` row per
  (user, SimpleFIN account) — only `Transaction` has the analogous
  constraint (`uq_transaction_account_simplefin_id`, and its own comment
  already anticipated this sync slice). Without this, every repeat sync
  creates duplicate `Account` rows and double-counts balances.
  confidence: high (directly mirrors an existing, already-battle-tested
  pattern in the same model file).
- **Transaction upsert reuses the existing `uq_transaction_account_simplefin_id`
  constraint** — no migration needed there, it already exists for exactly
  this purpose. confidence: high.
- **Upsert must never touch `Transaction.category_id`** on update — only
  SimpleFIN-owned fields (`amount`, `description`, `posted_at`, `pending`)
  are overwritten on a repeat sync. A user's manual categorization must
  survive a pending→posted transition or an amount correction.
  confidence: high.
- **Never delete a local `Transaction` based on absence from a sync
  response** — a `start-date`-windowed response omitting a transaction the
  app already has does not mean the bank removed it; upsert-only, no
  deletion. confidence: high.
- **Incremental sync window**: `start-date` = the account's last successful
  sync time minus 5 days (SimpleFIN's own documented overlap
  recommendation — see `research.md`), full 90-day max range on first sync
  per account. `end-date` = now. confidence: high (directly sourced from
  current docs, not guessed).
- **Pending-transaction `posted_at`**: `posted` is `0` for pending
  transactions in SimpleFIN's response, but `Transaction.posted_at` is
  `NOT NULL` in our schema. Resolution: use `transacted_at` if present,
  else the sync's own run date, as a placeholder — corrected automatically
  once the transaction truly posts and the next sync upserts it (same
  `simplefin_transaction_id`, stable key). Not relaxing the column to
  nullable. confidence: medium (a real design call; low blast radius since
  self-correcting on the next sync).
- **Partial per-account failure inside a `200`**: SimpleFIN's `errlist`/
  `errors` array means one broken linked institution shouldn't fail the
  whole sync. Resolution: sync succeeding accounts, surface failed ones in
  the response body (not a top-level error). confidence: medium (shape
  sourced from docs; exact response field name is a test-planning
  decision).
- **Rate-limit tracking**: client-side counter on `User`
  (e.g. a rolling-window timestamp list or count + window-start), capped
  conservatively below 24/day, checked before calling SimpleFIN — returns
  `429` without an outbound call if exceeded. Rolling-window (not
  calendar-day) specifically to sidestep needing to know SimpleFIN's own
  reset semantics (undocumented) — a rolling window is conservative
  regardless of which semantics SimpleFIN actually uses, and enforcement
  there is graduated (warns before disabling), which further lowers the
  cost of the app's cap being imperfect. confidence: medium (ASSUMPTION:
  exact cap number and storage shape are test-planning's call; the
  rolling-window *strategy* is the resolved part).
- **Response body size cap on the outbound `/accounts` GET**: apply the same
  "no unbounded read" discipline the `/connect` security review already
  established for this codebase (see `spec/simplefin-connect.md` Notes,
  finding #3) — but sized for an accounts+transactions payload, not the
  few-hundred-byte access URL exchange. confidence: medium (principle:
  high; exact byte cap: test-planning's call — propose something in the
  low-single-digit MB range as a starting point).
- **Response shape**: `POST /api/simplefin/sync` returns structured counts
  (accounts synced, transactions new vs. updated, any partial-failure
  detail) rather than a bare `{"status": "ok"}` — matches
  `transactions.md`'s pattern of returning meaningful shape, not just a
  status string. confidence: medium.

## Non-Goals
- Scheduled/cron automation of sync — still deferred, per `changes/002`'s
  own non-goal. This slice is on-demand only.
- Auto-categorization — deferred per `context/mvp-scope.md`.
- Backfill beyond SimpleFIN's 90-day max range (no multi-request pagination
  to fetch older history).
- Webhooks/push notification-driven sync — not offered by SimpleFIN per
  current docs.

## Build skills
- `app-security` — same category of review that caught 4 real findings on
  `simplefin-connect.md` (SSRF, redirect bypass, unbounded body, unvalidated
  shape). This slice adds a new outbound authenticated call and a new
  DB-write upsert path; worth the same focused pass.

## Grill

### Tensions & Structure

#### Category assignment survives repeat sync
- **Status:** resolved
- **Context:** Upserting a `Transaction` on repeat sync (by
  `(account_id, simplefin_transaction_id)`) could naively overwrite every
  column, including `category_id` — silently wiping a user's manual
  categorization the next time that transaction's amount/pending state
  changes upstream.
- **Decision:** Upsert only SimpleFIN-owned fields (`amount`, `description`,
  `posted_at`, `pending`). `category_id` is never touched by sync.
- **Confidence:** high
- **Consequences:** `spec/simplefin-sync.md`'s Done-when must include an
  explicit test: categorize a transaction, re-sync with an amended amount
  from SimpleFIN, confirm `category_id` is unchanged.
- **Alternatives considered:** Full-row overwrite (rejected — data loss);
  insert-only, skip on conflict (rejected — pending→posted transitions
  would never update).

#### Account upsert has no DB-level uniqueness today
- **Status:** resolved
- **Context:** `Account.simplefin_account_id` has no unique constraint,
  unlike `Transaction`'s analogous, already-battle-tested constraint. A
  naive upsert-by-query-then-insert-if-missing has a race condition, and
  without the constraint, a bug (or a retried request) silently creates
  duplicate `Account` rows that double-count balances.
- **Decision:** Add a migration:
  `UniqueConstraint("user_id", "simplefin_account_id")` on `Account`,
  before this slice is built.
- **Confidence:** high
- **Consequences:** New migration file, generated during `build`. No
  application code in this plan — HARD GATE respected.
- **Alternatives considered:** App-level "check then insert" without a DB
  constraint (rejected — race condition, and inconsistent with how
  `Transaction` already solved the identical problem).

#### Deletion/absence semantics
- **Status:** resolved
- **Context:** A `start-date`-windowed sync response omitting a
  previously-seen transaction doesn't mean it was deleted at the bank —
  it may just be outside the requested window, or briefly absent due to a
  provider hiccup.
- **Decision:** Sync is upsert-only. Never deletes a `Transaction` based on
  its absence from a response.
- **Confidence:** high
- **Consequences:** None — this is the safe default, no schema change.
- **Alternatives considered:** Soft-delete transactions absent for N
  consecutive syncs (rejected — unnecessary complexity, no evidence
  SimpleFIN ever signals real deletion this way).

#### Pending transaction has no real `posted_at`
- **Status:** assumption
- **Context:** SimpleFIN's `posted` field is `0` (epoch) when a transaction
  is pending, but `Transaction.posted_at` is `NOT NULL` in our schema.
- **Decision:** Use `transacted_at` if the response provides it, else the
  sync run's own date, as a placeholder. Gets corrected for free once the
  transaction posts and the next sync upserts the real `posted` value.
- **Confidence:** medium
- **Consequences:** `spec/simplefin-sync.md` needs a test: a pending
  transaction synced, then re-synced after "posting," ends up with the
  real posted date.
- **Alternatives considered:** Migrate `posted_at` to nullable (rejected —
  broader schema change than this slice needs, and every other consumer
  of `posted_at` — the transactions list/month filter — assumes non-null).

#### Rate-limit tracking strategy
- **Status:** assumption
- **Context:** SimpleFIN enforces 24 req/day per token, with graduated
  (warn-then-disable) enforcement, and undocumented reset-window
  semantics (calendar day vs. rolling 24h — genuinely couldn't confirm
  from current docs).
- **Decision:** Track client-side via a rolling window (not calendar-day),
  capped conservatively below 24, checked before every outbound call.
  Rolling window is conservative under either of SimpleFIN's possible
  actual semantics, sidestepping the need to know which one is real.
- **Confidence:** medium
- **Consequences:** `spec/simplefin-sync.md`'s test-planning picks the
  exact cap number and storage shape (new `User` columns vs. a small
  table).
- **Alternatives considered:** No client-side tracking, rely on SimpleFIN's
  own enforcement (rejected in Refutation below — real stakes, cheap
  insurance); a full sync-log table for audit trail (rejected as more
  than this on-demand, low-volume use case needs).

### Terminology

#### "Sync" vs. "Connect"
- **Status:** resolved
- **Context:** Checked for collision — `context/mvp-scope.md` already
  separates these cleanly ("Connect a SimpleFIN Access URL" item 1 vs.
  "Scheduled sync of accounts + transactions" item 2), and
  `simplefin-connect.md`'s own Notes already point forward to "the sync
  slice" using that exact word.
- **Decision:** No change. "Sync" = pulling data via an existing
  connection; "Connect" = establishing the connection. Consistent
  throughout context/ and spec/ already.
- **Confidence:** high
- **Consequences:** None.
- **Alternatives considered:** n/a — no real collision found.

### Prior-Decision Conflicts

#### mvp-scope.md's "Scheduled sync" wording vs. 002's on-demand-only non-goal
- **Status:** resolved
- **Context:** `context/mvp-scope.md` item 2 literally says "Scheduled sync
  of accounts + transactions." Read naively, that could pull cron/APScheduler
  scope back into this slice — but `changes/002/plan.md` already made a
  deliberate call to defer scheduling until "the manual path is proven."
- **Decision:** Keep 002's decision. This slice builds the on-demand,
  callable sync only. Scheduling remains explicitly deferred, not silently
  dropped.
- **Confidence:** high
- **Consequences:** None to existing specs — reaffirms, doesn't change,
  002's non-goal.
- **Alternatives considered:** Build scheduling now since mvp-scope.md's
  wording nominally calls for it (rejected — overrides a deliberate,
  recorded prior decision without a deliberate reason to; "proven manual
  path first" still holds, nothing has changed that would justify
  revisiting it).

#### Response body size cap — same category of finding as `/connect`'s security review
- **Status:** resolved
- **Context:** `spec/simplefin-connect.md`'s Notes record an "unbounded
  response body" finding fixed post-hoc during that slice's security
  review. This slice makes a second, larger outbound call
  (`GET /accounts`) with no size discipline planned yet.
- **Decision:** Apply the same principle proactively this time — bounded
  read on the sync's outbound call too — rather than waiting to
  rediscover the same category of finding in another after-the-fact
  review.
- **Confidence:** medium (principle: high; exact byte cap: test-planning's
  call, since it depends on realistic payload size for real
  account/transaction volumes).
- **Consequences:** `spec/simplefin-sync.md`'s Notes should carry this
  forward explicitly so `app-security`'s pass on this slice checks it
  from the start instead of finding it again.
- **Alternatives considered:** Defer to the security pass like last time
  (rejected — the whole point of a prior-decision conflict check is to
  not pay for the same lesson twice).

### Refutation
- **Strongest argument against this plan:** The simplest version skips the
  client-side rate limiter entirely — it's the most complex single piece
  of this slice, SimpleFIN already enforces its own limit server-side, and
  actual call volume here is inherently low (on-demand, a human clicking a
  button, not an automated poller). Building app-side tracking might be
  solving a problem that mostly can't happen given the low-volume trigger.
- **Resolution:** Proceed with a minimal version anyway (a counter, not a
  queue/audit system). The failure mode isn't hypothetical-volume risk,
  it's accident risk — a double-click, a retried request from a flaky
  connection, a future feature (like a "refresh" button with no debounce)
  — and the cost of guessing wrong here is real (a disabled token means
  re-issuing a Setup Token from SimpleFIN's UI, i.e. friction on Sam's
  actual bank connection, not just test data). Graduated enforcement
  (found during research) means the app's cap doesn't need to be
  perfectly tuned to be useful — it just needs to exist as a backstop.

## Open Questions
See `open-questions.md` for full detail.
- 🟡 Not-connected-user response code (`409`) — affects: `simplefin-sync.md`
- 🟡 Rate-limit cap number + storage shape — affects: `simplefin-sync.md`
- 🟡 Response body size cap (bytes) for `/accounts` — affects:
  `simplefin-sync.md`
- 🟡 Sync response shape (exact JSON keys for counts/partial failures) —
  affects: `simplefin-sync.md`
- 🟡 Pending-transaction `posted_at` placeholder — affects:
  `simplefin-sync.md`
