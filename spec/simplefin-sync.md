---
status: planned
depends_on: [simplefin-connect.md]
---

# SimpleFIN sync: pull accounts + transactions

## Does
Lets a connected real user pull their current account balances and
transactions from SimpleFIN into the app, on demand (not scheduled — see
`changes/003-simplefin-sync/plan.md` Non-Goals). Upserts `Account` and
`Transaction` rows keyed by their SimpleFIN ids so repeat syncs update
rather than duplicate, and never overwrites a transaction's user-assigned
`category_id`.

## Done when
- [Placeholder — auto-test-planning will fill this in]

## Integration test contract
[Placeholder — auto-test-planning will fill this in]

## Tests
No test exists yet — auto-test-planning will produce the contract,
auto-test-writer will produce the test.

## Notes
- Created by auto-plan-grill from `changes/003-simplefin-sync/plan.md` — read
  that plan's `## Grill` and `open-questions.md` before writing the contract;
  several structural decisions (upsert-without-clobbering-category_id,
  no-delete-on-absence, pending-transaction `posted_at` handling,
  rate-limit strategy) are already resolved there, not open for
  re-litigation, only for exact-value pinning (cap numbers, status codes,
  response keys — see `open-questions.md`).
- Requires a migration before this can be built:
  `UniqueConstraint("user_id", "simplefin_account_id")` on `Account` (see
  plan's Grill — `Transaction` already has the analogous constraint,
  `Account` doesn't yet).
- Response-body size cap on the outbound `/accounts` GET carries forward
  the same discipline `spec/simplefin-connect.md`'s security review
  established for the `/connect` exchange — don't let this slice
  rediscover that finding from scratch.
- `context/testing.md` already flags that `/connect`'s mock-the-exchange
  decision must NOT be assumed to carry over to `/accounts` polling —
  verify independently whether the public demo bridge's `/accounts`
  endpoint is safely repeatable across test reruns before deciding this
  slice's mock boundary.
