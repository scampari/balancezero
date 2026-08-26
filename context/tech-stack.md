# Tech stack

- **Backend**: Flask, converted to a pure JSON API (no server-rendered templates for app pages — login/budget/categories/transactions all become API endpoints). Existing Flask app, SQLAlchemy models, and CSRF-protected form routes are being replaced at the route layer; the data model underneath stays.
- **Frontend**: React SPA, separate from the Flask process. Talks to the Flask API over HTTP. Use the `frontend-design`/shadcn plugin tooling already installed for this Claude Code setup.
- **Auth**: session-cookie auth replaced by JWT access + refresh tokens. Access token in memory only; refresh token in an httpOnly/Secure/SameSite=Strict cookie, stored server-side in a revocable table — fixes the known revocation gap deliberately rather than reintroducing it in JWT form. Full detail and rationale in `security-requirements.md`.
- **Database**: relational. Postgres in production, SQLite acceptable for local dev. Data model (User, Account, Category, Transaction, BudgetAllocation) already exists in `models.py` and is not being redesigned — extend, don't replace.
- **Deploy target**: self-hosted, on the user's own hardware — a lightweight k3s cluster, reachable only over Tailscale (private tailnet, no Funnel, no public ingress). Decided 2026-08-26, replacing AWS EKS (see Superseded decisions below). k3s specifically (not plain Docker Compose) to preserve the original Kubernetes-portfolio value that motivated EKS in the first place, without AWS cost or the heavier EKS operational surface.
- **CI/CD**: Docker + GitHub Actions.
- **Bank data provider**: Plaid, replacing SimpleFIN (see `context/plaid-integration.md`). Sync is polling-only (`/transactions/sync`, no webhooks) — a direct consequence of the private-tailnet-only deploy target, since Plaid's webhook push would require public ingress via Tailscale Funnel.

## Superseded decisions
The project's original scope doc (`~/Desktop/CICD/BALANCEZERO-SCOPE.md`, 2026-07-31) chose server-rendered Flask templates specifically *to avoid a frontend-framework detour*, and explicitly deferred the ECS-vs-EKS choice until the app was closer to done. Both were deliberately overridden on 2026-08-10 in favor of a portfolio-quality modern UI and locking EKS early enough to parallelize infra work. Not an oversight — a conscious scope-increase tradeoff, made with the original reasoning in view.

**AWS EKS → self-hosted k3s over Tailscale (2026-08-26):** EKS was never built (only decided — no infra work existed yet), so this swap had zero implementation sunk cost. Full rationale and the grill that produced it: `changes/004-plaid-and-self-host/grill-findings.md`.

**SimpleFIN → Plaid (2026-08-26):** Full replacement, not additive. `spec/simplefin-connect.md` was built and tested; superseded anyway per the user's explicit choice after being shown the cheaper "keep both" alternative directly. See the same grill-findings.md.
