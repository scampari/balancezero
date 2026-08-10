# Tech stack

- **Backend**: Flask, converted to a pure JSON API (no server-rendered templates for app pages — login/budget/categories/transactions all become API endpoints). Existing Flask app, SQLAlchemy models, and CSRF-protected form routes are being replaced at the route layer; the data model underneath stays.
- **Frontend**: React SPA, separate from the Flask process. Talks to the Flask API over HTTP. Use the `frontend-design`/shadcn plugin tooling already installed for this Claude Code setup.
- **Auth**: session-cookie auth replaced by JWT access + refresh tokens. Access token in memory only; refresh token in an httpOnly/Secure/SameSite=Strict cookie, stored server-side in a revocable table — fixes the known revocation gap deliberately rather than reintroducing it in JWT form. Full detail and rationale in `security-requirements.md`.
- **Database**: relational. Postgres in production, SQLite acceptable for local dev. Data model (User, Account, Category, Transaction, BudgetAllocation) already exists in `models.py` and is not being redesigned — extend, don't replace.
- **Deploy target**: AWS EKS (Kubernetes), decided deliberately over ECS/Fargate specifically to demonstrate Kubernetes skills as part of this portfolio project. This is a heavier operational surface than Fargate — expect real setup work (cluster, node groups, ingress, IAM roles for service accounts).
- **CI/CD**: Docker + GitHub Actions.

## Superseded decisions
The project's original scope doc (`~/Desktop/CICD/BALANCEZERO-SCOPE.md`, 2026-07-31) chose server-rendered Flask templates specifically *to avoid a frontend-framework detour*, and explicitly deferred the ECS-vs-EKS choice until the app was closer to done. Both were deliberately overridden on 2026-08-10 in favor of a portfolio-quality modern UI and locking EKS early enough to parallelize infra work. Not an oversight — a conscious scope-increase tradeoff, made with the original reasoning in view.
