# BalanceZero

A YNAB-style zero-based budgeting web app, connected to real bank data via
[Plaid](https://plaid.com/). Every dollar of income gets assigned to a
category each month (income − allocated = 0), and unspent/overspent category
balances roll forward month to month.

Built as a portfolio/cornerstone project applying a full DevOps pipeline
(Docker, CI/CD, Kubernetes) and dedicated web security practices to one real
application, rather than practice repos.

## Status

Flask JSON API + React SPA with JWT auth, a working budget view, transaction
categorization, and Plaid bank integration (Link-based connect + cursor-based
transaction sync, both tested against Plaid's real Sandbox). Next up:
self-hosted deployment on a k3s cluster reachable only over Tailscale. See
`spec/` for what's built and `changes/` for the rationale behind each phase —
including the deliberate pivots from SimpleFIN to Plaid and from AWS EKS to
self-hosting (`changes/004-plaid-and-self-host/`).

## Design

Two users from day one: a real account (real Plaid connection, real bank
data) and a seeded demo account (synthetic data, no real bank connection) —
so the app can be shown publicly without ever exposing real financial data.

Full scope, data model, Plaid integration details, and security requirements:
see `context/` (architectural decisions) and `spec/` (what each slice of
behavior does and how it's tested).

## Stack

- Flask JSON API backend, React (Vite + TypeScript) SPA frontend
- JWT auth: short-lived access token (memory only, never persisted) +
  server-side-revocable refresh token (httpOnly cookie)
- Plaid for bank data — Link `public_token` → encrypted-at-rest
  `access_token` (Fernet), polling-only `/transactions/sync` (no webhooks,
  by design — see `context/plaid-integration.md`)
- Postgres (dev and prod both use it — see `context/tech-stack.md`)
- Docker, GitHub Actions CI/CD
- Deploy target: self-hosted k3s over Tailscale, private tailnet only, no
  public ingress (decided — see `context/tech-stack.md`), not yet built

## Local development

Plaid credentials are required (free —
[dashboard.plaid.com](https://dashboard.plaid.com), Sandbox keys):

```
export PLAID_CLIENT_ID=...   # from your Plaid dashboard
export PLAID_SECRET=...      # Sandbox secret, from the same page
```

Then one-command start (Postgres via Docker, both servers, demo data seeded
automatically):

```
./dev.sh
```

Open http://localhost:5173 and log in as `demo` / `demo-pw` — a seeded
account with sample categories, allocations, and transactions to interact
with. Re-running `dev.sh` is safe; it won't wipe your data (the demo seed
skips itself if the demo user already exists, and the dev database is a
separate, persistent Docker volume from the one the test suites use).

Ctrl+C stops both servers; the database keeps running
(`docker compose stop dev-db` if you want to stop that too).

### Running the test suites

Backend (pytest, against a separate, disposable test database):
```
source venv/bin/activate
docker compose up -d test-db
python -m pytest
```

Without real `PLAID_CLIENT_ID`/`PLAID_SECRET` in the environment, the tests
that exercise live Plaid Sandbox calls skip themselves (clearly labeled);
everything else runs. With real Sandbox credentials exported, the full suite
runs against Plaid's actual Sandbox API — see `context/testing.md` for why
these calls are real rather than mocked. One live-Sandbox test occasionally
fails on a transient Plaid-side hiccup (~1 run in 3); rerun if that happens.

Frontend e2e (Playwright, drives a real browser against the real backend):
```
cd frontend
npx playwright test
```

### Manual setup (if you'd rather not use dev.sh)

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
docker compose up -d dev-db
export SECRET_KEY=local-dev-secret-not-for-production
export DATABASE_URL=postgresql://balancezero_dev:balancezero_dev@localhost:55433/balancezero_dev
export PLAID_ENCRYPTION_KEY=$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
export PLAID_CLIENT_ID=...   # from your Plaid dashboard
export PLAID_SECRET=...      # Sandbox secret
flask db upgrade
python3 seed_demo.py
python3 app.py      # backend on :5002
cd frontend && npm install && npm run dev   # frontend on :5173, separate terminal
```

Note: `dev.sh` pins a fixed local-only `PLAID_ENCRYPTION_KEY` so restarts
don't invalidate stored Plaid connections; if you generate a fresh key per
shell (as above), reconnecting after each restart is expected.

Backend runs on port 5002 (5000 conflicts with macOS's AirPlay Receiver,
5001 is used by an unrelated exercise from this project's originating
course). Frontend runs on Vite's default, 5173.
