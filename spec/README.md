# BalanceZero — spec index

YNAB-style zero-based budgeting app. See `context/mvp-scope.md` for full feature scope and `changes/001-api-spa-rewrite/plan.md` for why the architecture is mid-rewrite (Flask JSON API + React SPA + JWT auth, replacing the original server-rendered/session-cookie app).

## Slices

| Spec | Status | Depends on |
|---|---|---|
| `auth.md` | built | — |
| `budget-api.md` | in-progress (category targets + `ready_to_assign` change) | auth |
| `frontend-app.md` | built | auth, budget-api |
| `transactions.md` | in-progress (`is_income` toggle) | auth, budget-api |
| `transactions-ui.md` | built | transactions, frontend-app |
| `simplefin-connect.md` | superseded by `plaid-connect.md` | auth |
| `simplefin-sync.md` | superseded by `plaid-sync.md` | simplefin-connect |
| `plaid-connect.md` | built | auth |
| `plaid-sync.md` | built | plaid-connect |
| `self-hosted-deploy.md` | built | frontend-app, budget-api |
| `accounts-api.md` | built | auth, plaid-connect |

SimpleFIN was replaced by Plaid and AWS EKS by a self-hosted k3s-over-Tailscale
deploy target, 2026-08-26 — see `changes/004-plaid-and-self-host/` for the
grill and plan behind the pivot. `simplefin-sync.md` merged (PR #1) as a
stub — no contract, never built — shortly before `plaid-sync.md` superseded
it (PR #2); both PRs landed on `main` in that order, so it's marked
superseded here rather than omitted.

Not yet sliced: CI/CD pipeline to the self-hosted cluster (explicit
non-goal of `changes/004`, see its plan for why). Each gets its own spec
when its slice starts (see `context/mvp-scope.md` for the full feature
list).
