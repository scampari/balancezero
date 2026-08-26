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
# Sandbox API. Get your own from the Plaid dashboard (free) and export them
# in your shell before running this script; connecting a bank in the running
# app won't work without them (link-token creation will 502).
export PLAID_CLIENT_ID="${PLAID_CLIENT_ID:?Set PLAID_CLIENT_ID from your Plaid dashboard}"
export PLAID_SECRET="${PLAID_SECRET:?Set PLAID_SECRET from your Plaid dashboard}"
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
