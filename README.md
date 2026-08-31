# BalanceZero

A YNAB-style zero-based budgeting web app, connected to real bank data via [Plaid](https://plaid.com/).
Every dollar of income gets assigned to a category each month (income − allocated = 0), and unspent or overspent category balances roll forward month to month.

Flask JSON API + React SPA with JWT auth, a working budget view, transaction categorization, and Plaid bank integration (Link-based connect + cursor-based transaction sync, both tested against Plaid's real Sandbox).
It runs self-hosted and private: reachable only over [Tailscale](https://tailscale.com/) at a `*.ts.net` HTTPS hostname, with no public ingress.

- **License:** [MIT](LICENSE)
- **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md)
- **Architecture decisions:** [`context/`](context/) — **behavior specs and tests:** [`spec/`](spec/) — **phase rationale:** [`changes/`](changes/)

## Contents

- [How it works](#how-it-works)
- [Stack](#stack)
- [Prerequisites](#prerequisites)
- [Setting up Plaid](#setting-up-plaid)
- [Local development](#local-development)
  - [Creating an account](#creating-an-account)
  - [Running the tests](#running-the-tests)
  - [Manual setup](#manual-setup-without-devsh)
- [Configuration reference](#configuration-reference)
- [Self-hosting over Tailscale](#self-hosting-over-tailscale)
- [Contributing](#contributing)
- [License](#license)

## How it works

Two users exist from day one: a real account (real Plaid connection, real bank data) and a seeded demo account (synthetic data, no real bank connection).
The demo account is why the app can be shown publicly without ever exposing real financial data.

Bank data flows one way: Plaid Link returns a `public_token`, the backend exchanges it for an `access_token`, encrypts that at rest with Fernet, and thereafter polls `/transactions/sync` with a stored cursor.
There are no webhooks by design — see [`context/plaid-integration.md`](context/plaid-integration.md).

## Stack

- Flask JSON API backend, React (Vite + TypeScript) SPA frontend
- JWT auth: short-lived access token (memory only, never persisted) + server-side-revocable refresh token (httpOnly cookie)
- Plaid for bank data — Link `public_token` → encrypted-at-rest `access_token` (Fernet), polling-only `/transactions/sync`
- Postgres (dev and prod both use it — see [`context/tech-stack.md`](context/tech-stack.md))
- Docker, GitHub Actions CI/CD
- Deploy: single-host `docker compose` or self-hosted k3s, both fronted by Tailscale, private tailnet only, no public ingress

## Prerequisites

- Python 3.13 and `python3-venv`
- Node 22+ and npm
- Docker and the Docker Compose plugin (for Postgres, and for deployment)
- A free Plaid account (see below)
- For self-hosting: a Tailscale account and one always-on Linux host

## Setting up Plaid

Plaid is free for development.
You need Sandbox credentials to run the app locally, and Production credentials only if you want to connect real banks on a deployed instance.

1. Sign up at [dashboard.plaid.com](https://dashboard.plaid.com).
   No credit card is required for Sandbox or Development.
2. Open **Team Settings → Keys**.
   Copy your **`client_id`** (one value, shared across environments) and your **Sandbox `secret`** (per-environment — the Sandbox and Production secrets are different values).
3. Put them in `.env` (see [Local development](#local-development)):
   ```
   PLAID_CLIENT_ID=<your client_id>
   PLAID_SECRET=<your Sandbox secret>
   PLAID_ENV=sandbox
   ```
4. Generate the at-rest encryption key for stored access tokens:
   ```sh
   python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
   ```
   Put the output in `PLAID_ENCRYPTION_KEY`.
   Keep it stable — if it changes, previously stored bank connections can no longer be decrypted and every user must re-link.

### Sandbox testing

In Sandbox, Plaid Link accepts the test credentials `user_good` / `pass_good` for any institution.
No real bank is contacted.

### Going to Production

Only needed for a real deployment connecting real accounts.
In the Plaid dashboard:

- Request Production access (**Team Settings → Keys → Request Production Access**).
  Approval is usually quick; some institutions (Chase, Fidelity, Schwab) need extra per-institution approval before they appear in Link.
- Set a Link use case under **Link → Link Customization → Data Transparency**.
- Register an **Allowed redirect URI** under **Team Settings → API**, matching your deployed host exactly (no query string), e.g. `https://balancezero.<tailnet>.ts.net/accounts`.
  Production requires `https://` and disallows plain `localhost` — the Tailscale hostname's cert satisfies this.
- Use the **Production** `secret` and set `PLAID_ENV=production` and `PLAID_REDIRECT_URI` to that URI.

## Local development

```sh
cp .env.example .env
```

Fill in at least `PLAID_CLIENT_ID`, `PLAID_SECRET`, and `PLAID_ENCRYPTION_KEY` (see [Setting up Plaid](#setting-up-plaid)).
`app.py` calls `load_dotenv()` at startup, so `.env` is picked up automatically; an explicit shell `export` still wins over it.

Then one command starts everything (Postgres via Docker, both servers, demo data seeded automatically):

```sh
./dev.sh
```

Open http://localhost:5173 and log in as `demo` / `demo-pw` — a seeded account with sample categories, allocations, and transactions.
Re-running `dev.sh` is safe: the demo seed skips itself if the demo user already exists, and the dev database is a separate, persistent Docker volume from the one the test suites use.

Ctrl+C stops both servers; the database keeps running (`docker compose stop dev-db` to stop that too).

> `dev.sh` pins a fixed local-only `PLAID_ENCRYPTION_KEY` so restarts don't invalidate stored Plaid connections.
> If you set your own fresh key per shell instead, reconnecting after each restart is expected.

Backend runs on port 5002 (5000 conflicts with macOS AirPlay Receiver).
Frontend runs on Vite's default, 5173.

### Creating an account

Signup is invite-only.
There is no HTTP endpoint that creates invite codes — only a local script.
Mint a single-use code, then use it on the `/signup` page:

```sh
python3 mint_invite.py                  # never expires
python3 mint_invite.py --expires-days 7
```

### Running the tests

Backend (pytest, against a separate, disposable test database):

```sh
source venv/bin/activate
docker compose up -d test-db
python -m pytest
```

Without real `PLAID_CLIENT_ID` / `PLAID_SECRET` in the environment, the tests that exercise live Plaid Sandbox calls skip themselves (clearly labeled); everything else runs.
With real Sandbox credentials exported, the full suite runs against Plaid's actual Sandbox API — see [`context/testing.md`](context/testing.md) for why these calls are real rather than mocked.
One live-Sandbox test occasionally fails on a transient Plaid-side hiccup (~1 run in 3); rerun if that happens.

Frontend e2e (Playwright, drives a real browser against the real backend):

```sh
cd frontend
npx playwright test
```

### Manual setup (without dev.sh)

```sh
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

## Configuration reference

All configuration is via environment variables (see [`.env.example`](.env.example) for the annotated list).

| Variable | Required | Purpose |
|---|---|---|
| `SECRET_KEY` | yes | Flask session / JWT signing key. Use a long random string. |
| `DATABASE_URL` | yes | Postgres connection string. |
| `PLAID_CLIENT_ID` | yes | Plaid client id (Team Settings → Keys). |
| `PLAID_SECRET` | yes | Plaid secret for the chosen environment. |
| `PLAID_ENV` | yes | `sandbox` (fake data) or `production` (real banks). |
| `PLAID_ENCRYPTION_KEY` | yes | Fernet key encrypting the stored Plaid `access_token` at rest. Must stay stable. |
| `PLAID_REDIRECT_URI` | OAuth banks only | Exact registered redirect URI for OAuth institutions. Leave unset otherwise. |
| `ALLOWED_ORIGIN` | dev only | Frontend origin allowed to call `/api/*` with credentials. Default `http://localhost:5173`. Prod is same-origin. |
| `TRUSTED_PROXY_COUNT` | prod behind proxy | Number of trusted reverse proxies, so the login/signup rate limiter keys on the real client IP. Default `0`. |
| `LOGIN_RATE_LIMIT_MAX` / `SIGNUP_RATE_LIMIT_MAX` | no | Max login / signup attempts per client IP per window. Defaults `10` / `5`. |

## Self-hosting over Tailscale

BalanceZero is designed to run on one machine you control, published only inside your [tailnet](https://tailscale.com/kb/1136/tailnet) at `https://balancezero.<tailnet>.ts.net`.
No ports are exposed to the public internet — the Tailscale container dials out.

Two deployment paths, same images and same same-origin topology (nginx proxies `/api` to the backend):

- **`docker compose` on a single host** — the lighter option. Full runbook: [`deploy/compose/README.md`](deploy/compose/README.md).
- **k3s (Kubernetes)** — uses the Tailscale Kubernetes operator and an L7 Ingress. Full runbook: [`deploy/README.md`](deploy/README.md).

### Tailscale setup (common to both)

1. Create a free account at [tailscale.com](https://tailscale.com/) and install Tailscale on the host and on any device you want to reach the app from.
2. In the [admin console](https://login.tailscale.com/admin): **DNS → HTTPS Certificates → Enable**.
   Without this, `tailscale serve` / the operator cannot issue the `*.ts.net` cert.
3. The MagicDNS name `balancezero` must be free in your tailnet — only one device can hold it.
   If an earlier deploy still owns it, tear that device down (and delete any stale `balancezero` device in the admin console) before bringing up the new one, or it registers as `balancezero-1` and the Plaid redirect URI stops matching.
4. Generate the credential the deployment needs:
   - **compose path:** a reusable, non-ephemeral auth key under **Settings → Keys → Generate auth key**.
   - **k3s path:** an OAuth client under **Settings → OAuth clients** with scopes `Devices Core` (write) and `Auth Keys` (write), tagged `tag:k8s-operator`; and a `tagOwners` entry in your ACLs for `tag:k8s-operator` / `tag:k8s`.
     Details in [`deploy/README.md`](deploy/README.md).

### Quick start (compose path)

```sh
cd deploy/compose
cp .env.prod.example .env.prod
# fill in .env.prod — generator commands are in the file; use Production Plaid keys
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

The backend runs `flask db upgrade` before gunicorn starts, so the schema is created on first boot.
Then register `https://balancezero.<tailnet>.ts.net/accounts` as an Allowed redirect URI in the Plaid dashboard, seed the demo user, and mint an invite:

```sh
CO="docker compose -f docker-compose.prod.yml --env-file .env.prod"
$CO exec backend python3 seed_demo.py     # demo / demo-pw
$CO exec backend python3 mint_invite.py   # single-use signup code
```

Verify from another tailnet device:

```sh
curl -sS https://balancezero.<tailnet>.ts.net/api/health   # -> {"status": "ok"}
```

For data migration from a dev database, backups, redeploys, and teardown, see the deploy runbooks.

## Contributing

Issues and pull requests are welcome.
Please read [CONTRIBUTING.md](CONTRIBUTING.md) first — it covers setup, the TDD workflow, running the suites, commit conventions, and how to report security issues privately.

## License

[MIT](LICENSE) © 2026 Sam Perez
