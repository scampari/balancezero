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
- [Placeholder — auto-test-planning will fill this in]

## Integration test contract
[Placeholder — auto-test-planning will fill this in]

## Tests
No test exists yet — auto-test-planning will produce the contract,
auto-test-writer will produce the test.

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
- Cursor storage granularity (`Account.plaid_sync_cursor` vs. a
  `User`/Item-level column) is an open, medium-confidence assumption — see
  `changes/004-plaid-and-self-host/open-questions.md`. Verify against real
  Plaid Sandbox behavior before locking the contract.
- Upsert must never touch `Transaction.category_id` — same principle as
  the original SimpleFIN-era design, this part does carry over unchanged.
- Response-body size cap on the outbound sync call carries forward the
  `/connect` security review's unbounded-response-body discipline
  (originally found on `spec/simplefin-connect.md`, now superseded, but
  the lesson isn't).
