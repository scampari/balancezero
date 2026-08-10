# BalanceZero

A YNAB-style zero-based budgeting web app, connected to real bank data via [SimpleFIN Bridge](https://www.simplefin.org/). Every dollar of income gets assigned to a category each month (income − allocated = 0), and unspent/overspent category balances roll forward month to month.

Built as a portfolio/cornerstone project applying a full DevOps pipeline (Docker, CI/CD, Kubernetes, AWS) and dedicated web security practices to one real application, rather than practice repos.

## Status

Rewritten from the original server-rendered scaffolding into a JSON API (Flask) + React SPA, with JWT auth, a working budget view, and transaction categorization. SimpleFIN bank integration and EKS deployment are next. See `spec/` for what's built and `changes/` for the rationale behind each phase.

## Design

Two users from day one: a real account (real SimpleFIN connection, real bank data) and a seeded demo account (synthetic data, no real bank connection) — so the app can be shown publicly without ever exposing real financial data.

Full scope, data model plan, SimpleFIN integration details, and security requirements: see `context/` (architectural decisions) and `spec/` (what each slice of behavior does and how it's tested).

## Stack

- Flask JSON API backend, React (Vite + TypeScript) SPA frontend
- JWT auth: short-lived access token (memory only, never persisted) + server-side-revocable refresh token (httpOnly cookie)
- Postgres (dev and prod both use it now — no more SQLite fallback in practice, see `context/tech-stack.md`)
- Docker, GitHub Actions CI/CD
- Deploy target: AWS EKS (decided — see `context/tech-stack.md`), not yet built

## Local development

One-command start (Postgres via Docker, both servers, demo data seeded automatically):

```
./dev.sh
```

Then open http://localhost:5173 and log in as `demo` / `demo-pw` — a seeded account with sample categories, allocations, and transactions to interact with. Re-running `dev.sh` is safe; it won't wipe your data (the demo seed skips itself if the demo user already exists, and the dev database is a separate, persistent Docker volume from the one the test suites use).

Ctrl+C stops both servers; the database keeps running (`docker compose stop dev-db` if you want to stop that too).

### Running the test suites

Backend (pytest, against a separate, disposable test database):
```
source venv/bin/activate
docker compose up -d test-db
python -m pytest
```

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
flask db upgrade
python3 seed_demo.py
python3 app.py      # backend on :5002
cd frontend && npm install && npm run dev   # frontend on :5173, separate terminal
```

Backend runs on port 5002 (5000 conflicts with macOS's AirPlay Receiver, 5001 is used by an unrelated exercise from this project's originating course). Frontend runs on Vite's default, 5173.
