---
status: built
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

> **`changes/008` rewrite (2026-08-27) — multi-institution.** `/sync` now
> fans out over every one of the user's `PlaidItem` rows. Superseded points
> (the sign-convention Notes, mutation-during-pagination handling, per-page
> commit, `removed` = authoritative delete all still stand):
>
> - The paginated loop moved into `_sync_one_item(user, item)` — per-item
>   `access_token` decrypt, per-item `sync_cursor` (was
>   `User.plaid_sync_cursor`, now `PlaidItem.sync_cursor`), per-item
>   mutation retry. On success it sets `PlaidItem.last_synced_at`.
> - `_upsert_account` takes the `PlaidItem` and sets `account.plaid_item_id`
>   on create **and** update (heals backfilled / re-linked rows).
> - **Response:** `{"items":[{id, institution_name, status:"ok"|"error",
>   error?, accounts_synced, transactions_added, transactions_modified,
>   transactions_removed}], "totals":{<summed counts>}, "ok": <all ok>}`.
> - **Status codes:** no `PlaidItem` rows → `409` (unchanged); ≥1 item
>   synced → `200` (with `ok` reflecting whether any failed); **every**
>   item failed → `502`; demo → `403`.
> - One item's failure never aborts the others — its committed pages and
>   advanced cursor stand, a retry resumes it.
> - **Tests:** `tests/test_plaid_sync.py` rewritten. Multi-item /
>   partial-failure / all-fail / `last_synced_at` / modified / removed run
>   offline against seeded `PlaidItem`s with a mocked `transactions_sync`;
>   the real first-pull and incremental-cursor tests stay
>   `@requires_plaid_sandbox`.

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
migration) from each account object's `balances.current` →
`Account.balance`, `balances.available` → `available_balance`; upserts
`added`/`modified` transactions (keyed by `(account_id,
plaid_transaction_id)`) — SimpleFIN-owned fields only (`amount`,
`description`, `posted_at`, `pending`), never `category_id`. **`amount`
must be negated** — Plaid's sign convention is the opposite of this
column's (see Notes, "Sign convention is flipped"). `description` maps
from Plaid's `name` field (verified via a real Sandbox transaction; Plaid
has no field literally called `description`). `posted_at` maps from
Plaid's `date` field. Hard-deletes `Transaction` rows named in `removed`.
After each page, `User.plaid_sync_cursor` is updated to that page's
`next_cursor` and committed — not deferred to the end of the whole sync.

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
- `tests/test_plaid_sync.py` § `"test_sync_without_token_returns_401"` —
  covers § error case: no access token.
- `tests/test_plaid_sync.py` § `"test_sync_as_demo_user_returns_403"` —
  covers § error case: demo user.
- `tests/test_plaid_sync.py` § `"test_sync_without_connection_returns_409"`
  — covers § error case: no Plaid connection.
- `tests/test_plaid_sync.py` § `"test_sync_plaid_outage_returns_502"` —
  covers § error case: Plaid network-level failure (mocked at the SDK
  layer — a real `access_token` from a real connect, only the sync call
  itself is mocked).
- `tests/test_plaid_sync.py` § `"test_sync_populates_accounts_and_transactions"`
  — covers § main contract: real Sandbox connect + sync, real DB
  assertions (`accounts_synced` matches distinct `Account` rows).
- `tests/test_plaid_sync.py` § `"test_sync_is_incremental_on_second_call"`
  — covers § Done-when: cursor persistence, proven behaviorally (second
  call shows 0 added) rather than by reading the column directly.
- `tests/test_plaid_sync.py` § `"test_sync_upserts_modified_transaction_without_touching_category"`
  — covers § contract: `modified` upsert, sign-convention negation (exact
  value assertion), and `category_id` preservation. Mocked second sync
  call (see file docstring for why); real connect, real first sync, real
  categorization through the actual `/api/categories` +
  `/api/transactions/<id>` endpoints.
- `tests/test_plaid_sync.py` § `"test_sync_deletes_removed_transaction"` —
  covers § contract: hard-delete on `removed`. Mocked second sync call,
  same reasoning as above.

8 of 8 confirmed red (404, no route yet) before commit — verified with
real Plaid Sandbox credentials (not just structurally; the 5
Sandbox-dependent tests actually ran and failed for the right reason, not
skipped). Full suite: 8 failed (all this file, all 404), 62 passed, 0
unexpected failures — 41.56s.

**Built.** All 8 green against real Sandbox. Two test-setup corrections
were needed while confirming green (documented inline in the test file,
neither changed the behavior under test): the incremental test originally
omitted its connect step (409 before ever reaching the cursor behavior),
and then raced Plaid's asynchronous historical update (a second sync
legitimately reporting *more* transactions while history was still
landing isn't a cursor failure) — fixed with a settle loop.

**Known accepted flake:** roughly 1 run in 3, one Sandbox-dependent test
(which one rotates) fails with the route's sanitized `502` during a live
call — transient Sandbox-side behavior, passes on rerun. Explicitly
accepted by the user (2026-08-26) rather than chased further; the
mutation-during-pagination handling below already eliminated the
reproducible cause, and the sanitized error (correct for production)
hides the residual one. If this ever needs diagnosing, add temporary
server-side logging of the swallowed exception in `sync()`.

## Notes
- **Sign convention is flipped from SimpleFIN's — the single most
  important correctness detail in this slice.** Plaid: positive `amount` =
  money leaving the account; negative = money entering. This app's
  `Transaction.amount` keeps SimpleFIN's convention (positive = inflow),
  unchanged. **Negate Plaid's `amount` on every write.** Caught by
  inspecting a real Sandbox transaction directly rather than assuming —
  see `context/plaid-integration.md`. Get this backwards and every synced
  transaction silently corrupts the budget math throughout the app, not
  just the transactions list.
- **`accounts_synced` must count distinct accounts, not sum per page.**
  Verified against a live Sandbox response: every page's `accounts` array
  repeats the full account list, not just accounts touched on that page.
  Naively summing `len(page["accounts"])` across pages would overcount
  whenever `has_more` triggers more than one page.
- **Real field mapping, verified against a live Sandbox transaction**
  (`user_transactions_dynamic`/`pass_good` test user): transaction
  `name` → our `description` (Plaid has no field called `description`);
  `date` → our `posted_at`; `amount` → our `amount`, negated (see above);
  `pending` → our `pending` directly, no transform. Account `balances.current`
  → our `balance`; `balances.available` → our `available_balance`.
- **Sandbox item initialization is asynchronous** — empirically, a freshly
  exchanged Sandbox `access_token` returns zero transactions for several
  seconds (`transactions_update_status` starts pending, reaches
  `INITIAL_UPDATE_COMPLETE` once ready). Not just a testing quirk — a real
  user's very first sync immediately after connecting could plausibly hit
  the same window and get 0 results. Not treated as an error case in this
  contract (a `200` with all-zero counts is still a valid, honest
  response) but flagged here so it isn't mistaken for a bug during build
  or manual testing — try again after a few seconds.
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
- **Found during build: `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION`
  is a real, documented, expected error** — Plaid raises it when the
  Item's data changes mid-pagination, which is *routine* right after
  connect while the historical update is still landing (exactly this
  slice's test setup, and plausibly a real user's first sync).
  Documented client behavior, now implemented in `sync()`: restart the
  whole pagination loop from the update's *starting* cursor (not the
  failed page's — safe because upserts are idempotent), bounded to 3
  retries; plus `count=500` per page (Plaid's documented mitigation —
  fewer pages, smaller mutation window). Treating it as a generic 502
  was the initial, wrong implementation.
- **Found during build: Plaid's SDK returns `date` as a native
  `datetime.date`**, not a string — no parsing needed when writing
  `posted_at`. Verified empirically against a live Sandbox response.

## Changes
- 004 (2026-08-26) — contract landed by auto-test-planning; three plan
  assumptions resolved with verified evidence (cursor is Item-scoped →
  `User.plaid_sync_cursor`; no response-size cap needed; response shape
  locked). Sign-convention flip discovered and documented before any
  code existed to get it wrong.
- 004 (2026-08-26) — 8 tests written, confirmed red with real Sandbox
  credentials.
- 004 (2026-08-26) — built. `sync()` route in `plaid_api.py`; migration
  `250dac683643` adds `User.plaid_sync_cursor`. Mutation-during-pagination
  handling added after live testing surfaced it (see Notes). All 8 green;
  one accepted transient Sandbox flake (see Tests).
- 008 (2026-08-27) — multi-institution. `/sync` loops every `PlaidItem`,
  per-item token + cursor + mutation-retry; per-item results + summed
  `totals` + `ok`; all-fail → `502`. Cursor moved `User → PlaidItem`
  (migration `035d62499d87`); `_upsert_account` tags `plaid_item_id`;
  `PlaidItem.last_synced_at` added. See the rewrite note above the contract
  and `changes/008-multi-institution-plaid/plan.md`.
- 011 (2026-08-27) — fresh-connection import cutoff. `_sync_one_item` skips
  any `added` / `modified` transaction dated before `PlaidItem.import_cutoff`
  (a fresh connect only imports transactions posted on/after the connect
  date — not the ~90 days of history Plaid's first sync returns). `NULL`
  cutoff = import everything. `removed` is unaffected (a no-op for anything
  never imported). Tests in `tests/test_plaid_sync.py`.
- 012 (2026-08-27) — Starting Balance on connect. When `_upsert_account`
  creates a brand-new local account, `_add_starting_balance` adds one
  synthetic "To Be Budgeted" transaction (`is_income=true`,
  `amount = account.balance`, `description="Starting Balance"`,
  `plaid_transaction_id=null`, dated at `PlaidItem.import_cutoff or
  today`). Pairs with the 011 import cutoff — the cutoff drops
  pre-connection history, this puts the resulting balance back into
  `ready_to_assign`. Created only on account creation (idempotent across
  re-syncs); skipped for a zero balance. Tests in `tests/test_plaid_sync.py`.
- 013 (2026-08-27) — auto-categorization by reuse. When `_upsert_transaction`
  creates a **new** row with no category (and not `is_income`), it copies
  the category from the user's most recent transaction with the same
  `description` (same merchant), via `api_helpers.infer_category_id` with a
  per-sync `description -> category_id` cache. Only on creation — a
  `modified` upsert never re-categorizes, so a user's filing survives.
  `tests/test_plaid_sync.py` +2.
- 015 (2026-08-27) — skip pending until posted. `_should_import` (wraps
  `_within_import_window`) drops any `added` / `modified` entry whose Plaid
  `pending` flag is true — it isn't imported until it settles and arrives
  again as non-pending (a `modified` on the same `transaction_id`, or a
  fresh `added` linked by `pending_transaction_id`). Skipped entries don't
  count toward `transactions_added` / `transactions_modified`. Synced rows
  are therefore always `pending = false`. `removed` for a never-imported
  pending entry stays a no-op. `tests/test_plaid_sync.py` +2.
- 016 (2026-08-27) — bug fix: a `NULL` `import_cutoff` no longer means
  "import everything" (that let a pre-011 item pull ~3 months on its first
  sync). `_import_cutoff(item)` returns `item.import_cutoff or
  item.created_at.date()`, and migration `8c14d99893c5` backfills the NULLs.
- 018 (2026-08-27) — account types + liability balances. `_upsert_account`
  now writes `Account.type` / `Account.subtype` from Plaid's
  classification (every sync, so pre-018 rows self-heal). For a `type` of
  `credit` or `loan` the balance is stored **negated** (`-abs(current)`) —
  Plaid reports a card's balance as a positive amount owed; this app's
  convention is that a balance is what you have. `_add_starting_balance`
  for a liability account writes the opening entry negative and
  `is_income=false` (carried debt, not money to budget). Migration
  `079c5813dbbb` (pure DDL). Depository accounts unchanged.
  `tests/test_plaid_sync.py` +3.
