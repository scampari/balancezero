# BalanceZero — spec index

YNAB-style zero-based budgeting app. See `context/mvp-scope.md` for full feature scope and `changes/001-api-spa-rewrite/plan.md` for why the architecture is mid-rewrite (Flask JSON API + React SPA + JWT auth, replacing the original server-rendered/session-cookie app).

## Slices

| Spec | Status | Depends on |
|---|---|---|
| `auth.md` | built | — |
| `budget-api.md` | planned | auth |
| `frontend-app.md` | not yet created | auth, budget-api |

Not yet sliced: SimpleFIN connection, scheduled sync, transaction categorization UI, EKS deploy/CI pipeline. Each gets its own spec when its slice starts (see `context/mvp-scope.md` for the full feature list these will cover).
