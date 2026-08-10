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

| `simplefin-connect.md` | planned | auth |

Not yet sliced: scheduled sync (`simplefin-sync.md`), EKS deploy/CI pipeline. Each gets its own spec when its slice starts (see `context/mvp-scope.md` for the full feature list, and `changes/002-simplefin-and-transactions/plan.md` for the current phase's rationale).
