#!/usr/bin/env bash
# Starts everything needed for local interactive use: the persistent dev
# database, the Flask backend, and the Vite dev server. Ctrl+C stops both
# servers (the database keeps running — it's meant to persist between runs).
#
# First run: also seeds the demo user (username: demo, password: demo-pw)
# with sample data, unless it's already there. See seed_demo.py.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

export SECRET_KEY="${SECRET_KEY:-local-dev-secret-not-for-production}"
export DATABASE_URL="${DATABASE_URL:-postgresql://balancezero_dev:balancezero_dev@localhost:55433/balancezero_dev}"
# Fixed local-only key so re-running dev.sh doesn't invalidate previously
# stored Plaid connections. Not for production — generate a real one there
# (Fernet.generate_key()) and manage it as a real secret.
export PLAID_ENCRYPTION_KEY="${PLAID_ENCRYPTION_KEY:-Cf36XJcRZYQp9YWjLnryvcDl-SZ7D1b01e8wnS9QJAk=}"
# No safe local default for these — they authenticate against Plaid's real
# API. Provide them either by exporting them in your shell before running
# this script, or (easier) by putting them in a gitignored .env file in this
# directory — app.py calls load_dotenv() on startup. Without them, connecting
# a bank in the running app won't work (link-token creation will 502).
# Only re-export what's already in the environment; leaving a var unset lets
# .env supply it (load_dotenv doesn't override vars that are already set,
# even to an empty string).
if [ -n "${PLAID_CLIENT_ID:-}" ]; then export PLAID_CLIENT_ID; fi
if [ -n "${PLAID_SECRET:-}" ]; then export PLAID_SECRET; fi
# OAuth institutions (Chase, BofA, ...) redirect the browser back mid-Link and
# need a redirect URI registered in the Plaid dashboard. For local dev that's
# http://localhost:5173/accounts (Plaid Sandbox accepts http://localhost).
if [ -n "${PLAID_REDIRECT_URI:-}" ]; then export PLAID_REDIRECT_URI; fi
export FLASK_APP=app.py
export FLASK_DEBUG="${FLASK_DEBUG:-1}"

echo "Starting dev database..."
docker compose up -d dev-db

echo "Waiting for dev database to be healthy..."
until [ "$(docker inspect --format='{{.State.Health.Status}}' balancezero-dev-db-1 2>/dev/null)" = "healthy" ]; do
  sleep 1
done

echo "Applying migrations..."
venv/bin/flask db upgrade

echo "Seeding demo data (skipped if already present)..."
venv/bin/python3 seed_demo.py

echo ""
echo "Starting Flask backend on http://localhost:5002 ..."
venv/bin/python3 app.py &
BACKEND_PID=$!

echo "Starting Vite dev server on http://localhost:5173 ..."
(cd frontend && npm run dev) &
FRONTEND_PID=$!

cleanup() {
  echo ""
  echo "Stopping servers..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo ""
echo "Ready — open http://localhost:5173 and log in as demo / demo-pw"
echo "Press Ctrl+C to stop."
wait
