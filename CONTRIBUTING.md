# Contributing to BalanceZero

Thanks for your interest.
BalanceZero is a portfolio project first, but issues and pull requests are welcome.

## Ground rules

- Be respectful. Assume good faith.
- This app handles real financial data. Security and correctness beat speed.
- Never commit secrets, real Plaid credentials, `.env`, `.env.prod`, database dumps, or `PLAID_ENCRYPTION_KEY` values.

## Before you start

- For anything larger than a small fix, open an issue first so we can agree on the approach.
- Read `context/` (architectural decisions) and `spec/` (behavior slices and how each is tested).
  Decisions like "Plaid over SimpleFIN", "self-host over AWS EKS", and "poll `/transactions/sync`, no webhooks" are deliberate and documented there.

## Development setup

See the "Local development" section of [`README.md`](README.md).
Short version:

```sh
cp .env.example .env        # fill in Plaid Sandbox credentials
./dev.sh                    # Postgres + backend + frontend + demo seed
```

Log in at http://localhost:5173 as `demo` / `demo-pw`.

## Workflow

1. Fork and branch from `main`. Branch names: `feature/short-description` or `fix/short-description`.
2. Follow the existing style. Match the surrounding code.
   - Python: keep functions small and single-purpose; no new lint failures.
   - Frontend: `cd frontend && npm run lint` must pass.
3. Write or update tests alongside the change (TDD is the norm here — see `spec/` and `context/testing.md`).
4. Run the full test suite locally (below). Green before you push.
5. Use [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): description`
   (e.g. `feat(budget): roll overspend forward`, `fix(plaid): handle ITEM_LOGIN_REQUIRED`).
6. Open a PR against `main`. Describe what changed and why, and link the issue.
   CI (GitHub Actions) must pass.

## Running the tests

Backend (pytest, separate disposable test database):

```sh
source venv/bin/activate
docker compose up -d test-db
python -m pytest
```

Without real `PLAID_CLIENT_ID` / `PLAID_SECRET` exported, tests that hit the
live Plaid Sandbox skip themselves (clearly labeled); everything else runs.
With Sandbox credentials exported, the full suite runs against Plaid's real
Sandbox API — see `context/testing.md` for why these are real, not mocked.
One live-Sandbox test occasionally fails on a transient Plaid hiccup
(~1 run in 3); rerun if that happens.

Frontend e2e (Playwright, real browser against the real backend):

```sh
cd frontend
npx playwright test
```

## Reporting security issues

Do not open a public issue for a security vulnerability.
Email sam.perez67@gmail.com with details and a way to reproduce.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
