# BalanceZero — spec index

YNAB-style zero-based budgeting app. See `context/mvp-scope.md` for full feature scope and `changes/001-api-spa-rewrite/plan.md` for why the architecture is mid-rewrite (Flask JSON API + React SPA + JWT auth, replacing the original server-rendered/session-cookie app).

## Slices

| Spec | Status | Depends on |
|---|---|---|
| `auth.md` | built | — |
| `budget-api.md` | built | auth |
| `frontend-app.md` | built | auth, budget-api |
| `transactions.md` | built | auth, budget-api |
| `transactions-ui.md` | built | transactions, frontend-app |
| `simplefin-connect.md` | superseded by `plaid-connect.md` | auth |
| `plaid-connect.md` | planned | auth |
| `plaid-sync.md` | planned | plaid-connect |
| `self-hosted-deploy.md` | planned | frontend-app, budget-api |

SimpleFIN was replaced by Plaid and AWS EKS by a self-hosted k3s-over-Tailscale
deploy target, 2026-08-26 — see `changes/004-plaid-and-self-host/` for the
grill and plan behind the pivot. `simplefin-sync.md` never made it past a
stub on an unmerged branch (draft PR #1) and isn't part of this history.

Not yet sliced: CI/CD pipeline to the self-hosted cluster (explicit
non-goal of `changes/004`, see its plan for why). Each gets its own spec
when its slice starts (see `context/mvp-scope.md` for the full feature
list).
