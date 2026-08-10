# Slicing: transactions UI + SimpleFIN connect/sync

> Date: 2026-08-10
> Status: planning

## What & Why

Closes the remaining gaps between the current app (auth + budget view, both working) and a genuinely usable local MVP: seeing and categorizing transactions (currently no way to do either through the app — only via `seed_demo.py`), and connecting a real SimpleFIN Bridge account to pull real bank data. Explicitly scoped to *local* usage — EKS deployment is a separate, later phase.

## Spec changes
- `spec/transactions.md` (new) — list + categorize transactions. First slice, no external dependency, works against existing demo data immediately.
- `spec/simplefin-connect.md` (new) — Setup Token → Access URL exchange, encrypted storage. Built and tested against SimpleFIN's real, public, reusable demo token (`aHR0cHM6Ly9iZXRhLWJyaWRnZS5zaW1wbGVmaW4ub3JnL3NpbXBsZWZpbi9jbGFpbS9ERU1PLXYyLUE4MEVDOUI5NDlGMjQxOEE0QzhE`) — no real bank account needed to build/test this.
- `spec/simplefin-sync.md` (new) — pulls accounts + transactions via the stored Access URL, respects the 24-requests/day cap and 90-day max range.

## Constraints
- Sequencing: transactions UI first (no external dependency, immediate interactive value), then SimpleFIN connect, then SimpleFIN sync (depends on connect).
- SimpleFIN work is built/tested against the public demo token first. The user has a real SimpleFIN Setup Token ready for their own bank, but it will NOT be typed into the conversation — it gets entered directly into the running app once the connect endpoint exists (or set as a local env var / passed via a local-only script), keeping it out of any transcript or shared context.
- Transactions have no `user_id` column — ownership is always through `Transaction.account_id` → `Account.user_id`, matching the existing `get_owned_category`-style pattern from `budget-api.md`.
- `seed_demo.py` gets adapted (not replaced) to run against the current app for local interactive use — it already produces data consistent with the budget math, just needs to stop assuming it owns the whole DB lifecycle in isolation.
- Local dev tooling (one-command start for both servers + demo seed) is in scope here since "something to interact with" requires actually running the app outside the Playwright harness.

## Non-Goals
- EKS/AWS deployment — separate, later phase.
- Scheduled/cron automation of the sync job — this phase builds the sync as an on-demand, callable operation; wiring it to run automatically on a schedule is a follow-up once the manual path is proven.
- Auto-categorization — explicitly deferred per `context/mvp-scope.md`.

## Build skills
- `app-security` — SimpleFIN Access URL encryption-at-rest is a real security requirement (SimpleFIN's own stated requirement, already noted in `context/simplefin-integration.md`), worth a focused pass.

## First slice
- `spec/transactions.md` — no dependency on SimpleFIN work, delivers immediate interactive value.

## Open Questions
- Exact sync trigger for this phase (a button in the UI vs. a CLI script) — left to `simplefin-sync.md`'s own test-planning.
- Whether `cryptography`'s Fernet (already a dependency, already referenced in `models.py`'s comments) is the actual encryption approach — confirm during `simplefin-connect.md`'s test-planning rather than assuming.
