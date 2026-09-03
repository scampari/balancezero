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
>   transactions_removed, transactions_linked}], "totals":{<summed counts>},
>   "ok": <all ok>}`. `transactions_linked` (added `changes/022`) counts
>   incoming transactions that were merged into a pre-existing manual row
>   rather than inserted as a new row — see § Manual-transaction adoption.
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
"transactions_modified": <int>, "transactions_removed": <int>,
"transactions_linked": <int>}` (per-item and summed into `totals` — see the
`changes/008` rewrite note above for the full multi-item shape).
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

#### Manual-transaction adoption (changes/022)

A user can enter a transaction manually (`POST /api/transactions`,
`plaid_transaction_id = null`) before the bank posts it. When the posted
transaction later arrives from Plaid, sync **adopts** the manual row in
place instead of inserting a second row that double-counts the money.

**Where:** inside `_upsert_transaction`, on the path that would otherwise
create a brand-new row (no existing row for `(account_id,
plaid_transaction_id)`). Applies to entries from **both** the `added` and
the `modified` loop — a transaction first seen while `pending` (held back
by `changes/015`) can arrive as a `modified` the first time it's eligible
to import.

**Match rule** — an incoming Plaid transaction adopts a manual row only
when **every** condition holds:
- same resolved `account_id`;
- `Transaction.plaid_transaction_id IS NULL` (not already linked);
- `Transaction.amount == -Decimal(str(plaid_txn["amount"]))` exactly — this
  app's sign convention, negated from Plaid's the same way the upsert
  negates it (see Notes, "Sign convention is flipped"). No tolerance.
- `abs(Transaction.posted_at - plaid_txn["date"]) <= 7 days`;
- normalized description similarity `>= 0.80` —
  `difflib.SequenceMatcher(None, a, b).ratio()` on each side lower-cased
  and reduced to alphanumerics separated by single spaces. **No substring
  shortcut** (a bare "Amazon" vs "AMAZON MKTPL\*1A2B" does *not* match).
  This is the strict end of the dial, chosen deliberately: it will miss a
  match whenever the typed description differs a lot from the bank's
  merchant string, and the user accepted that in exchange for near-zero
  false positives.
- the row's `description` is not the synthetic `"Starting Balance"`
  sentinel (`changes/012`) — that row is never adopted.

**Ambiguity resolution:** if more than one manual row qualifies, adopt the
one with the smallest date distance; break ties by highest similarity
ratio, then lowest `id`. Exactly one manual row is adopted per incoming
Plaid transaction; other qualifying rows are left as-is (the user deletes
any leftover near-duplicate themselves).

**On adoption:** the manual row's `plaid_transaction_id` is stamped and its
Plaid-owned fields (`amount`, `description`, `posted_at`, `pending`,
`transfer`) are overwritten from the Plaid payload. `category_id` and
`is_income` are **never** touched — same invariant that protects a
categorized synced row from a later `modified`. `infer_category_id` does
**not** run on an adopted row (the manual row already carries whatever
category the user or the manual-add path gave it). `created_at` keeps the
manual row's original value.

**Counting:** an adopted transaction increments `transactions_linked` for
that item — never `transactions_added` or `transactions_modified`. The
counter is part of `_EMPTY_COUNTERS`, so the mutation-during-pagination
reset zeroes it and the per-item `totals` accumulation sums it with no
special-casing.

**Idempotency & removal:** once adopted the row has a
`plaid_transaction_id`, so every later sync finds it by id on the normal
`modified` path — it is never re-matched and never re-counted as linked. A
subsequent Plaid `removed` for that `transaction_id` hard-deletes the row
like any other synced transaction (it *is* that transaction now).

No migration: `plaid_transaction_id` is already nullable, and stamping it
can't violate `uq_transaction_account_plaid_id` because adoption only runs
when no row matched that `(account_id, plaid_transaction_id)` to begin
with.

**Cases** (all offline — mocked `transactions_sync`, real DB, seeded
`PlaidItem` + `Account`, same harness as the `changes/008`+ offline tests):

1. **Close match is adopted.** A manual row on the synced account with the
   exact (negated) amount, `posted_at` 3 days before the Plaid `date`, a
   description that normalizes to `>= 0.80` similarity, and a user-assigned
   `category_id`. Incoming `added` entry for the posted transaction.
   **Then:** no new `Transaction` row is created (row count for the account
   is unchanged); the manual row now has the Plaid `transaction_id`;
   `category_id` is unchanged; `amount`, `description`, `posted_at`,
   `pending`, `transfer` now equal the Plaid values; response
   `transactions_linked == 1` and `transactions_added == 0` for that item.
2. **Amount mismatch → not adopted.** Manual row identical to case 1 except
   the amount differs by `0.01`. **Then:** a new row is inserted,
   `transactions_added == 1`, `transactions_linked == 0`, the manual row is
   untouched (`plaid_transaction_id` still `null`).
3. **Outside the date window → not adopted.** Manual row identical to case
   1 except `posted_at` is 10 days from the Plaid `date`. **Then:** a new
   row is inserted; the manual row is untouched.
4. **Dissimilar description → not adopted.** Manual row identical to case 1
   except the description normalizes to `< 0.80` similarity. **Then:** a
   new row is inserted; the manual row is untouched.
5. **Ambiguous → closest wins.** Two manual rows both satisfy the rule; one
   is 1 day from the Plaid `date`, the other 5 days. **Then:** only the
   1-day row is adopted (`plaid_transaction_id` stamped); the 5-day row
   stays manual (`plaid_transaction_id` still `null`); `transactions_linked
   == 1`.
6. **"Starting Balance" is never adopted.** The synthetic opening row
   (`description == "Starting Balance"`, `plaid_transaction_id null`) whose
   amount and date happen to line up with an incoming transaction. **Then:**
   a new row is inserted for the incoming transaction; the Starting Balance
   row is untouched.
7. **Already-linked row on re-sync.** A row that already has a
   `plaid_transaction_id` (from a prior adoption or a normal import); the
   next sync delivers that `transaction_id` in `modified`. **Then:** the
   existing row is updated on the normal `modified` path, no duplicate is
   created, `transactions_linked == 0`.
8. **Pre-entered income is adopted.** A manual row with `is_income == true`
   and `category_id == null` (a paycheck entered before it lands) that
   satisfies the match rule. **Then:** the row is adopted, `is_income`
   stays `true`, `category_id` stays `null`, `transactions_linked == 1`.

#### Per-account import cutoff (changes/023)

When a user adds accounts to an already-linked bank via Plaid Link update
mode (`spec/plaid-connect.md` § POST /api/plaid/items/&lt;id&gt;/update-link-token),
the new accounts arrive on the **next** `/api/plaid/sync` — Plaid replays
their history as `added` entries on the Item's existing cursor. Without a
per-account cutoff, an account added months after first link would dump up to
~90 days of history into the budget. So a newly-added account tracks from the
day it is added, while the accounts present at first link keep the Item-level
`import_cutoff`.

**Schema:** new `Account.import_cutoff` (Date, **nullable**, no backfill
migration — pure DDL, one column). `NULL` means "no per-account cutoff — use
the Item's."

**Effective cutoff:** `_account_import_cutoff(account, item)` returns
`account.import_cutoff or _import_cutoff(item)` (`_import_cutoff` is the
existing `item.import_cutoff or item.created_at.date()` from `changes/016`).

**Stamping:** `_upsert_account` sets `account.import_cutoff = date.today()`
**only when it creates the row for an Item that has synced before**
(`is_new and item.last_synced_at is not None`). Never on update. Never during
an Item's first-ever sync — those accounts keep `NULL`, so the
"connect, then sync days later" path stays retry-safe and byte-for-byte
identical to pre-`changes/023` behaviour.

**Gating:** both the `added` and the `modified` loop resolve
`_account_for(txn["account_id"])` **first**; if it returns `None` (the
`account_id` is absent from the page's `accounts` array and from the DB), the
entry is skipped — no import, no counter increment, not an error.
`_should_import` / `_within_import_window` take the resolved `Account` and
gate on `_account_import_cutoff(account, item)` instead of the Item cutoff.

**Starting Balance:** `_add_starting_balance` dates the synthetic opening row
at `_account_import_cutoff(account, item)` — today's date for a
newly-added account, the Item cutoff (via the `NULL` fallback) for a
first-link account.

**Cursor is unchanged** — still Item-scoped (`context/plaid-integration.md`).
Only the import cutoff becomes per-account.

**Cases** (all offline — mocked `transactions_sync`, real DB, seeded
`PlaidItem` + `Account`, same harness as the `changes/008`+ offline tests;
`_mock_sync_response` gains an `accounts` argument so a page can introduce a
new account):

1. **New account on an already-synced Item gets today's cutoff.** Seed a
   `PlaidItem` with `last_synced_at` set and `import_cutoff` 60 days ago, plus
   one existing `Account` A. Mock one page whose `accounts` array is
   `[A, B]` (B new) and whose `added` array has one txn on B dated 30 days
   ago and one dated today. **Then:** `Account` B is created with
   `import_cutoff == date.today()`; the 30-days-ago txn on B is **not**
   imported; the today txn on B **is** imported; B gets a `"Starting Balance"`
   row dated `date.today()`; account A is untouched (its `import_cutoff` stays
   `NULL`).
2. **Pre-today history for the new account is skipped in bulk.** Same setup as
   case 1 but B's `added` array has 5 txns spanning 90 days ago → today.
   **Then:** only the txns dated `>= date.today()` are imported;
   `transactions_added` for that item counts exactly those; no error.
3. **First-ever sync still imports from the Item cutoff (`NULL` account
   cutoff).** Seed a `PlaidItem` with `last_synced_at IS None` and
   `import_cutoff` 7 days ago. Mock one page: `accounts` `[C]`, `added` = one
   txn on C dated 3 days ago (after the Item cutoff) and one dated 14 days ago
   (before it). **Then:** `Account` C is created with `import_cutoff IS NULL`;
   the 3-days-ago txn is imported, the 14-days-ago txn is skipped (the Item
   cutoff still governs, via the `NULL` fallback); C's `"Starting Balance"`
   row is dated at the Item cutoff (7 days ago), not today. Identical to
   pre-`changes/023` behaviour.
4. **Existing `NULL`-cutoff account keeps Item-cutoff behaviour on a later
   sync.** Seed a `PlaidItem` with `last_synced_at` set and `import_cutoff` 30
   days ago, plus an existing `Account` D with `import_cutoff IS NULL` (synced
   before this change). Mock a page: `accounts` `[D]`, `added` = one txn on D
   dated 20 days ago and one dated 40 days ago. **Then:** the 20-days-ago txn
   is imported, the 40-days-ago txn is skipped (Item cutoff via the `NULL`
   fallback); D's `import_cutoff` stays `NULL` (not stamped on update).
5. **`added` entry for an unknown `account_id` is skipped, not an error.**
   Mock a page: `accounts` `[E]`, `added` = one txn whose `account_id` is
   neither in that `accounts` array nor in the DB. **Then:** the sync
   returns `200`; that entry is not imported and not counted; no exception is
   raised (documents `_account_for → None → continue`).

No migration beyond the one nullable `Date` column. The existing
`changes/011` import-cutoff cases and `changes/015` skip-pending cases must
still pass unchanged — same accounts, same effective cutoff via the `NULL`
fallback; the `_should_import` signature change is internal.

## Tests
- `tests/test_plaid_sync.py` § `"test_sync_without_token_returns_401"` —
  covers § error case: no access token.
- `tests/test_plaid_sync.py` § `"test_sync_flags_transfers_from_personal_finance_category"`
  — covers § transfer detection (028): plain `TRANSFER_OUT`/`TRANSFER_IN`
  and `LOAN_PAYMENTS_CREDIT_CARD_PAYMENT` → `transfer=True`; `*_P2P`
  detail and non-credit-card `LOAN_PAYMENTS` → `transfer=False`.
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
- `tests/test_plaid_sync.py` § `"test_sync_adopts_a_matching_manual_row_and_is_idempotent_on_resync"`
  — covers § Manual-transaction adoption cases 1 + 7: the adopt itself
  (no new row, id stamped, `category_id` kept, Plaid fields applied) and
  idempotency when the transaction is re-delivered as `modified`.
- `tests/test_plaid_sync.py` § `"test_sync_requires_an_exact_amount_match_to_adopt"`
  — covers § case 2: a cent-off row is not adopted even when its date is
  closer.
- `tests/test_plaid_sync.py` § `"test_sync_only_adopts_within_a_seven_day_window"`
  — covers § case 3: a row 10 days out is excluded even with a perfect
  description.
- `tests/test_plaid_sync.py` § `"test_sync_requires_description_similarity_to_adopt"`
  — covers § case 4: a `< 0.80` description is not adopted even on an
  exact-date, exact-amount row.
- `tests/test_plaid_sync.py` § `"test_sync_adopts_the_closest_candidate_when_several_qualify"`
  — covers § case 5: nearer date wins among qualifying rows.
- `tests/test_plaid_sync.py` § `"test_sync_never_adopts_the_synthetic_starting_balance_row"`
  — covers § case 6: the reserved `"Starting Balance"` description is never
  a candidate; a non-reserved lookalike is.
- `tests/test_plaid_sync.py` § `"test_sync_keeps_an_already_linked_row_on_the_normal_modified_path"`
  — covers § case 7: a row that already has a `plaid_transaction_id` goes
  through the normal `modified` upsert, `transactions_linked` unaffected by
  it.
- `tests/test_plaid_sync.py` § `"test_sync_preserves_is_income_when_adopting_a_manual_row"`
  — covers § case 8: a pre-entered income row keeps `is_income` / null
  `category_id` through adoption.
- `tests/test_api_helpers.py` § `"TestDescriptionSimilarity"` — covers the
  `description_similarity` helper: case/punctuation normalization, the
  ratio being `difflib` on the normalized text, and pairs either side of
  the `0.80` line.
- `changes/023` — § Per-account import cutoff: no test exists yet —
  test-writer will produce the 5 cases (`tests/test_plaid_sync.py`, all
  offline) when this slice is built.

All 14 confirmed red before implementation — the 8 sync cases failed
`transactions_linked == 1` (`0 == 1`, adoption not implemented); the 6
helper cases failed `AttributeError` (`description_similarity` didn't
exist). **Built** — all 14 green, full suite 259 passed / 6 skipped. One
locked-test setup fix during build:
`test_sync_adopts_a_matching_manual_row_and_is_idempotent_on_resync`
seeded the manual row's description as `"Blue Bottle"`, which scores 0.59
against the Plaid name — below the agreed 0.80 threshold, so the row could
never be adopted by a contract-correct implementation. Widened to
`"BLUE BOTTLE COFFEE 0123"` (0.94) to match its sibling tests; no
assertion changed, and the overwrite assertion is now a real check.

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
- 019 (2026-08-27) — transfer detection. `_upsert_transaction` sets
  `Transaction.transfer` when Plaid's `personal_finance_category.primary`
  is `TRANSFER_IN`, `TRANSFER_OUT`, or `LOAN_PAYMENTS` (a credit-card
  payment). Missing/blank category → false. Feeds the budget-math
  exclusion in `spec/budget-api.md`. Migration `ca283921af94`.
  `tests/test_plaid_sync.py` +1.
- 021 (2026-08-27) — auto-created credit-card payment category. When
  `_upsert_account` handles an `account.type == "credit"` account it calls
  `_ensure_payment_category(user, account)`: finds/creates a top-level
  `"Credit Card Payments"` group and a child `Category` bound to the card
  via `payment_account_id`. Idempotent — a gate query plus the unique
  constraint (+ `IntegrityError` swallow) mean re-sync / re-link never
  duplicates. No backfill migration: the hook runs for every credit
  account on every sync. Depository/loan accounts get nothing.
  `tests/test_plaid_sync.py` +2. Budget math in `spec/budget-api.md`.
- 022 (2026-08-28) — manual-transaction adoption. Before
  `_upsert_transaction` inserts a new row it calls
  `_adopt_manual_transaction` to find an unlinked manual row on the same
  account (exact negated amount, `posted_at` within 7 days,
  `api_helpers.description_similarity` `>= DESCRIPTION_MATCH_THRESHOLD`
  (0.80) with no substring shortcut, never the `"Starting Balance"`
  sentinel; nearest date then strongest match then lowest id wins).
  Adoption stamps `plaid_transaction_id` and overwrites the Plaid-owned
  fields only — `category_id` / `is_income` survive, `infer_category_id` is
  skipped. `_upsert_transaction` returns `"linked"`; both `_sync_one_item`
  loops route that to `transactions_linked` (already in `_EMPTY_COUNTERS`,
  so per-item results, `totals`, and the mutation-restart reset carry it).
  No migration (`plaid_transaction_id` already nullable).
  `tests/test_plaid_sync.py` +8, `tests/test_api_helpers.py` (new) +6.
  Full suite 259 passed / 6 skipped. See § Manual-transaction adoption and
  `changes/022-link-manual-on-sync/plan.md`.
- 023 (2026-08-28) — contract landed by test-planning. New
  `Account.import_cutoff` (Date, nullable, no backfill) + an effective
  per-account cutoff (`account.import_cutoff or _import_cutoff(item)`).
  `_upsert_account` stamps `date.today()` only on a genuinely-new account of
  an already-synced Item (`is_new and item.last_synced_at is not None`); both
  sync loops resolve `_account_for` first and skip an entry whose account is
  unknown; `_should_import` and `_add_starting_balance` move to the
  per-account cutoff. Lets a user add accounts at an already-linked bank
  (`spec/plaid-connect.md` § update-link-token) and have them track from the
  add-date, not the Item's original connect date. See § Per-account import
  cutoff and `changes/023-add-accounts-update-mode/plan.md`. Not yet built.
- 028 (2026-09-01) — narrowed transfer detection. `_is_transfer` now
  reads `personal_finance_category.detail`, not just `primary`: `TRANSFER_IN` /
  `TRANSFER_OUT` are a transfer unless the detail ends `_P2P` (Venmo, Zelle,
  PayPal, Cash App — money that leaves the budget to someone else), and
  `LOAN_PAYMENTS` is a transfer only for `LOAN_PAYMENTS_CREDIT_CARD_PAYMENT`
  (a student / auto / mortgage / personal loan payment is a real expense).
  On the next sync `_upsert_transaction` overwrites `transfer` from the
  payload, so previously mis-flagged rows self-heal. Paired with
  `spec/budget-api.md` 028 (a categorized transfer still counts as spend).
  `tests/test_plaid_sync.py` `test_sync_flags_transfers_from_personal_finance_category`
  expanded. `changes/028-transfer-flag-respects-category`.
- 029 (2026-09-03) — contract landed by test-planning. `_ensure_payment_category`
  is **skipped for debt-payoff cards**: `_upsert_account` calls it only when
  `account.type == "credit" and not account.debt_payoff`. `_is_transfer` and
  every other sync behavior is unchanged — a credit-card payment is still
  flagged `transfer` (the budget counts it once the user files it to a
  category, `spec/budget-api.md` 029). Contract:
  - **Setup:** a synced `PlaidItem` whose payload includes two
    `type == "credit"` accounts — one whose local `Account.debt_payoff` is
    already `true` (e.g. converted earlier via `PATCH /api/accounts`, so its
    old payment `Category` now has `payment_account_id IS NULL`), one with
    `debt_payoff = false`.
  - **Action:** `POST /api/plaid/sync`.
  - **Expected:** after sync, **no** `Category` has `payment_account_id`
    pointing at the flagged account, and no `"Credit Card Payments"` group is
    created on its behalf; the `debt_payoff = false` account still gets its
    payment category (unchanged 021 behavior). Re-running the sync does not
    resurrect the flagged card's payment category.
  - `tests/test_plaid_sync.py` § `"test_sync_skips_payment_category_for_a_debt_payoff_card"`
    — covers § the two-credit-account contract (flagged card gets/keeps no
    payment category across two syncs; the non-flagged card still does).
    `changes/029-credit-card-debt-payoff`. Built 2026-09-03 — one-line
    guard in `_upsert_account`: `account.type == "credit" and not
    account.debt_payoff`.
