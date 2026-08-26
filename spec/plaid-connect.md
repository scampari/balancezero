---
status: planned
depends_on: [auth.md]
---

# Plaid connect: Link token → access_token/item_id exchange

## Does
Lets the real (non-demo) user connect a bank account via Plaid Link:
backend mints a `link_token`, the frontend opens Plaid Link with it, the
user completes the flow, and the backend exchanges the resulting
`public_token` for a permanent `access_token` + `item_id`, storing the
access token encrypted at rest. Replaces `spec/simplefin-connect.md`
(superseded — see `changes/004-plaid-and-self-host/plan.md`).

## Done when
- [Placeholder — auto-test-planning will fill this in]

## Integration test contract
[Placeholder — auto-test-planning will fill this in]

## Tests
No test exists yet — auto-test-planning will produce the contract,
auto-test-writer will produce the test.

## Notes
- Created by auto-plan-grill from `changes/004-plaid-and-self-host/plan.md`
  — read that plan's `## Grill` and `open-questions.md` before writing the
  contract. Two endpoints, not one: `POST /api/plaid/link-token` then
  `POST /api/plaid/connect` — Plaid's flow requires minting a `link_token`
  before Link can open, unlike SimpleFIN's single-call exchange.
- Requires a migration: rename `User.simplefin_access_url_encrypted` →
  `plaid_access_token_encrypted`, add `User.plaid_item_id`, rename
  `Account.simplefin_account_id` → `plaid_account_id` (also adding the
  `UniqueConstraint("user_id", "plaid_account_id")` that was already
  missing before), rename `Transaction.simplefin_transaction_id` →
  `plaid_transaction_id`. No data-preserving path from the old column —
  see plan's Grill, "Real SimpleFIN connection may already exist locally."
- New required env vars: `PLAID_CLIENT_ID`, `PLAID_SECRET`,
  `PLAID_ENCRYPTION_KEY` (replaces `SIMPLEFIN_ENCRYPTION_KEY`). No
  default/fallback on the encryption key, same discipline as before.
- Whether this slice can be built/tested fully against Plaid Sandbox
  without `spec/self-hosted-deploy.md` existing yet (OAuth-institution
  redirect URI) is flagged as an open question — see
  `changes/004-plaid-and-self-host/open-questions.md`, "Sandbox
  OAuth-institution coverage." Verify directly against current Plaid
  Sandbox docs before assuming either way.
- Frontend needs the `react-plaid-link` package — not present in
  `frontend/package.json` today. Frontend work itself is out of scope for
  this spec's backend contract but the dependency should be flagged when
  build starts.
