# Slicing: JSON API + React SPA + JWT auth rewrite

> Date: 2026-08-10
> Status: planning

## What & Why

BalanceZero is being rebuilt from a server-rendered Flask app (session-cookie auth, Jinja templates) into a JSON API backend with a separate React SPA frontend, ending in an AWS EKS deployment. This supersedes the original scope doc's deliberate choice to stay server-rendered — done knowingly, trading more build scope for a portfolio-quality modern UI and Kubernetes deployment experience. The rewrite also fixes a known security gap: Flask's stateless session cookie has no server-side revocation, so a copied cookie survives "logout." The new JWT scheme uses a server-side-revocable refresh token specifically to close that gap, not reintroduce it.

## Spec changes
- `spec/auth.md` (new) — JWT login/refresh/logout, replacing session-cookie auth. First slice, entry point — nothing else in the new architecture works without it.
- `spec/budget-api.md` (new) — converts existing server-rendered budget routes (`budget_view`, `create_category`, `set_allocation`) to JSON API endpoints. Depends on `auth.md` for the protected-route pattern.
- `spec/frontend-app.md` (new) — React SPA shell: Vite + TypeScript + React Router, API client, login page, budget page. Depends on both `auth.md` and `budget-api.md` existing as real endpoints to call.

Not detailed yet, sequenced after these three (per `context/mvp-scope.md`): SimpleFIN connection flow, scheduled sync job, transaction categorization UI, EKS deploy + CI/CD pipeline. Each becomes its own spec when its slice starts.

## Context changes
None beyond what's already in `context/` from today's architecture discussion (`tech-stack.md`, `simplefin-integration.md`, `security-requirements.md`, `mvp-scope.md`).

## Constraints
- Backend: Flask converted to pure JSON API — no more Jinja templates for app pages. Existing SQLAlchemy models (`User`, `Account`, `Category`, `Transaction`, `BudgetAllocation`) reused as-is, not redesigned.
- Frontend: Vite + TypeScript + React Router. Plain SPA, no server-side rendering — matches "React talking to Flask as an API" exactly, avoids unused Next.js machinery.
- Auth: JWT access token (~15 min expiry) + refresh token. Refresh tokens are stored server-side (new DB table) so logout/revocation actually works — this is the fix for the flagged session-revocation gap. A bare stateless JWT pair was explicitly rejected for reintroducing the same flaw.
- CSRF: dropped for API routes — bearer-token-in-Authorization-header auth isn't vulnerable to the same cross-site attack `flask_wtf.CSRFProtect` guards against (browsers don't auto-attach custom headers cross-origin). `flask_wtf`/CSRFProtect gets removed from the API routes, not translated 1:1.
- CORS: Flask API must allow the React dev server's origin (and later, the production frontend origin) — needs explicit CORS config, not open-to-all.
- Testing: no test framework exists in the project yet. First slice must also stand up pytest (backend) as part of its scope — this isn't optional infrastructure, it's required for test-writer/build's TDD loop to function at all.
- Data isolation: every new API endpoint must follow the existing `get_owned_category()`-style ownership-check pattern (direct column comparison, not trusting a join) — see `context/security-requirements.md`.
- First slice bundles auth + budget-api + frontend-app as one delivered unit (user's explicit choice) — a working login-to-budget-page flow, not just a login screen — even though they're tracked as three separate specs for testing granularity.

## Non-Goals
- SimpleFIN integration — later slice, not this change.
- EKS/deploy work — later slice, not this change.
- Auto-categorization, multi-account households, budget templates, reports — deferred per `context/mvp-scope.md`, not MVP at all.
- Public signup / multi-tenant auth beyond the existing 2 users (real + demo).
- Redesigning the data model — reused as-is.

## Build skills
- `frontend-build` — React/TypeScript/Vite tooling and conventions.
- `boilerplate-cicd` — project has no test framework or CI yet; needed to stand up pytest and a basic GitHub Actions run before/alongside the first slice.
- `app-security` — auth/token slice is security-sensitive (this is literally the slice fixing a flagged vulnerability); worth a focused pass on the JWT/refresh implementation specifically.

## First slice
- `spec/auth.md` — the literal entry point: JWT issuance, refresh, revocable logout, and the protected-route pattern everything else depends on. `budget-api.md` and `frontend-app.md` follow immediately after in the same delivered batch, per the user's scope choice, but `auth.md` is where build starts.

## Open Questions
- Exact refresh-token rotation policy (rotate-on-use vs fixed-lifetime) — left to test-planning to pin down as part of `auth.md`'s contract.
- Where CORS allowed-origins config lives for local dev vs. eventual EKS production (env var vs hardcoded) — revisit once frontend-app's dev server setup is concrete.
- Whether `flask-jwt-extended` (mature, handles refresh/blocklist patterns) or a hand-rolled `PyJWT` implementation is used — recommend `flask-jwt-extended` for the built-in blocklist support matching the revocation requirement; confirm during `auth.md` test-planning.

## Grill

### Tension: token storage location was unspecified, and CSRF-removal reasoning silently depended on it
**Challenge:** The plan dropped CSRF protection with the reasoning "bearer tokens don't auto-attach cross-site" — but never stated where the frontend actually stores the access/refresh tokens. That reasoning only holds if tokens live in JS-accessible storage (localStorage or an Authorization header sourced from memory), not if they end up in a cookie. For a financial app, localStorage exposes both tokens to any XSS bug; a naive "both tokens in httpOnly cookies" fix reintroduces CSRF for the whole API, contradicting the plan's own reasoning.
**Resolution:** Access token held in memory only (never persisted, lost on refresh — acceptable, since it's silently re-minted). Refresh token in an httpOnly, Secure, SameSite=Strict cookie, invisible to JS and therefore safe from XSS token theft. Only the `/api/refresh` endpoint touches the cookie, so only that one endpoint needs CSRF protection (e.g. a double-submit token or origin check) — the rest of the API keeps the plan's original bearer-token/no-CSRF reasoning intact.
**Write-back:** `context/security-requirements.md` updated with the token-storage decision and the narrowed CSRF scope (see below).

### Tension: does bundling auth+budget-api+frontend-app as "first slice" break the one-slice-at-a-time build discipline?
**Challenge:** The engineering/build flow processes one spec at a time (`build → commit → refactor → next slice`), each with its own locked test contract. The plan's "first slice bundles three specs" language could be misread as one giant slice with one contract, which would violate that discipline and produce a single hard-to-review commit.
**Resolution:** Not a real conflict once clarified — "bundled" means these three specs get built back-to-back with no scope-decision pause between them (matching the user's wish for a working login→budget flow soon), not that they collapse into one spec or one commit. Build still processes `auth.md`, commits, refactors, then `budget-api.md`, commits, refactors, then `frontend-app.md`, same as any other sequence of slices.
**Write-back:** Plan's "First slice" section stands as written; no context/ change needed, this was a plan-clarity issue, not an architecture decision.

### Terminology: "session" vs. "token pair"
**Collision:** `context/security-requirements.md` and the original scope doc use "session" to describe Flask's cookie-based auth state. The new architecture has no server-side "session" concept in that sense anymore — auth state is an access/refresh token pair, with only the refresh token persisted (in the new revocation table).
**Resolution:** "Session" is retired as a term for anything going forward in this project. Use "access token" and "refresh token" specifically. The revocation table is a "refresh token store," not a "session store."
**Write-back:** `context/security-requirements.md` updated to use token-pair terminology instead of "session."

### Refutation: is the whole rewrite oversized?
**Argument:** The original scope doc already identified a smaller fix for the flagged security gap — add Flask-Session + Redis for a real server-side, revocable session store — which resolves the actual security defect without a JSON-API/SPA/JWT rewrite at all. Paired with Tailwind/htmx for a modern look, that's a materially smaller change achieving most of the same value (fixed security gap + modern-looking UI), and it's the path the original plan's own reasoning pointed toward.
**Resolution:** Argument holds on its merits, but doesn't change the plan — the user was presented with this exact tradeoff twice during slicing (once before context/ was seeded, once after seeing the scope doc's original reasoning explicitly) and confirmed the React SPA rewrite both times, prioritizing portfolio-quality UI over minimal scope. Documented here so the tradeoff is on the record, not because it changes the decision.

## Test planning result

### Spec files created
- `spec/README.md` (new) — slice index for the project, greenfield bootstrap.
- `spec/auth.md` (new) — first slice. Full integration test contract for `POST /api/login`, `POST /api/refresh`, `POST /api/logout`, and the protected-route pattern.

### Mock boundaries
- Real: Postgres (via Docker, not SQLite — see `context/testing.md`).
- No external services in scope for `auth.md` — SimpleFIN isn't touched until its own later slice.

### Context updates
- `context/testing.md` (new) — pytest + real-Postgres-via-Docker test infrastructure decision.

### Test infrastructure notes
- pytest not yet installed — needs adding to `requirements.txt` (or a new `requirements-dev.txt`) as part of building this slice.
- Needs a Postgres test instance reachable in local dev and CI — Docker Compose service, separate DB from dev/prod.
- Refresh-token reuse detection (theft signal → mass-revoke) intentionally deferred past this slice — see `spec/auth.md` Notes. Not forgotten, just out of walking-skeleton scope.
