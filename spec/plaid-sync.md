---
status: planned
depends_on: [plaid-connect.md]
---

# Plaid sync: cursor-based transaction pull

## Does
Lets a connected user pull current account balances and transactions from
Plaid via `/transactions/sync`, on demand (not scheduled). Upserts
`Account`/`Transaction` rows, deletes transactions Plaid explicitly reports
as `removed`, and never overwrites a transaction's user-assigned
`category_id`. Replaces `spec/simplefin-sync.md` (superseded — was only
ever a stub, never built).

## Done when
- A connected user can trigger a sync and have their accounts' balances
  and their transactions (new, changed, and removed) reflected locally.
- The demo user can never sync (no Plaid connection exists to sync from).
- A never-connected user gets a clear precondition error, not a confusing
  empty success.
- Re-syncing is incremental (uses the stored cursor), not a full re-pull
  every time, and picks up exactly where the last sync left off — even if
  Plaid's data spans multiple pages (`has_more`).
- A transaction the user has categorized keeps that category through any
  number of future syncs, even if Plaid reports it `modified`.
- Progress is saved per page, not all-or-nothing — a sync that fails
  partway through (e.g. a Plaid outage on page 3 of 5) keeps pages 1–2's
  results and their cursor position, rather than losing everything.

## Integration test contract

### POST /api/plaid/sync

**Setup:** An authenticated, non-demo user with an existing Plaid
connection (`plaid_access_token_encrypted` set — via a real `/connect`
exchange in tests, same as `plaid-connect.md`'s pattern, not a raw DB
write, so the access token is real and usable against Sandbox).
**Action:** `POST /api/plaid/sync`, `Authorization: Bearer <access token>`.
**Input:** No body.
**Expected output:** `200`, JSON
`{"accounts_synced": <int>, "transactions_added": <int>,
"transactions_modified": <int>, "transactions_removed": <int>}`.
**Side effects:** Decrypts the stored `access_token`, calls
`/transactions/sync` with `cursor=User.plaid_sync_cursor` (`None` on first
sync), looping while the response's `has_more` is `true` — accumulating
each page isn't required; each page is applied and committed
independently (see Done-when). Per page: upserts `Account` rows (keyed by
`(user_id, plaid_account_id)`, the constraint added in `plaid-connect.md`'s
migration) with fresh `balance`/`available_balance`/`balance_date`;
upserts `added`/`modified` transactions (keyed by
`(account_id, plaid_transaction_id)`) — SimpleFIN-owned fields only
(`amount`, `description`, `posted_at`, `pending`), never `category_id`;
hard-deletes `Transaction` rows named in `removed`. After each page,
`User.plaid_sync_cursor` is updated to that page's `next_cursor` and
committed — not deferred to the end of the whole sync.

#### Error cases
- **When no/invalid access token, Then** `401`.
- **When the authenticated user is the demo user, Then** `403` — the demo
  user has no Plaid connection to sync from, same guard as `/connect` and
  `/link-token`.
- **When the user has no Plaid connection (`plaid_access_token_encrypted`
  is `None`), Then** `409` — same precondition-vs-input-error reasoning as
  `plaid-connect.md`'s Notes (nothing wrong with the request, the account
  state just isn't ready for it).
- **When Plaid's `/transactions/sync` call fails (HTTP error status OR a
  network-level failure — outage, timeout), Then** `502`, the same
  sanitized generic error as `plaid-connect.md`'s routes. Whatever pages
  already completed before the failure keep their committed state and
  cursor position (see Done-when) — a retried sync resumes, doesn't
  restart.

## Tests
No test exists yet — auto-test-writer will produce these next.

## Notes
- Created by auto-plan-grill from `changes/004-plaid-and-self-host/plan.md`
  — read that plan's `## Grill` before writing the contract. Several
  decisions there are corrections to what `spec/simplefin-sync.md` would
  have done, not carryovers — don't assume SimpleFIN's design applies
  unchanged:
  - **No date windowing.** `/transactions/sync` is cursor-based: first call
    omits `cursor` (full 90-day history), later calls pass `next_cursor`
    (incremental only). No 5-day-overlap logic needed.
  - **Delete on `removed`, don't just upsert-and-never-delete.** Plaid's
    `removed` array (`transaction_id` + `account_id`) is an explicit,
    authoritative deletion signal — hard-delete the local `Transaction`
    when it appears there. This is the opposite of what was planned for
    SimpleFIN's windowed-absence ambiguity; don't default to the earlier
    no-delete reasoning.
  - **No rate-limit tracking.** Plaid's real limits (50 req/min per Item)
    make SimpleFIN's rolling-window counter unnecessary. Don't build it.
- **Resolved (verified against current Plaid docs, high confidence):
  cursor is `User.plaid_sync_cursor`, not `Account`-level.** Plaid's docs
  are explicit: the cursor is Item-scoped by default — one cursor covers
  every account under the Item — and only becomes per-account if requests
  filter by `account_id`, which this slice's contract doesn't do (no
  reason to, at single-institution scope). The plan's original
  `Account.plaid_sync_cursor` guess was wrong; corrected here rather than
  carried forward. Needs a migration: `User.plaid_sync_cursor` (nullable
  `String`, `None` = never synced).
- **Resolved: no response-body size cap needed, correcting the plan's
  carried-forward assumption.** The plan proposed carrying forward
  `/connect`'s unbounded-response-body defense "just in case," but that
  defense existed because SimpleFIN's claim URL was user-supplied
  (attacker could point it anywhere). `/transactions/sync` goes through
  the same official Plaid SDK, against the same fixed, trusted,
  environment-selected host as `plaid-connect.md`'s calls — not
  client-derived, not attacker-controlled. `plaid-connect.md`'s Notes
  already established this exact reasoning for skipping SimpleFIN's
  SSRF/redirect defenses; it applies here too and wasn't re-examined when
  the plan wrote this assumption. No streamed-read size cap needed.
- **Per-page commit is a deliberate design choice, not just an
  implementation detail** — process and commit each `/transactions/sync`
  page as it arrives (updating the cursor each time) rather than
  accumulating every page in memory and committing once at the end. Keeps
  memory bounded on a large `has_more` history and makes a mid-sync
  failure resumable instead of all-or-nothing. Mirrors
  `plaid_api.py`'s existing per-request-scoped style, nothing exotic.
- Upsert must never touch `Transaction.category_id` — same principle as
  the original SimpleFIN-era design, this part does carry over unchanged.
- Whether `/transactions/sync` can report partial per-account failure
  inside an otherwise-`200` response (the way SimpleFIN's `/accounts` had
  an `errlist` array) — **not verified**, don't assume either way. The
  response does have a `transactions_update_status` field whose exact
  semantics weren't checked closely enough to design an error case around
  it. If `auto-build` finds real partial-failure behavior during
  implementation, that's a legitimate correction to make then — flagged
  here rather than guessed into the contract now.
