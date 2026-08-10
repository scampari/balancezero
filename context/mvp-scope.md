# MVP scope

From `~/Desktop/CICD/BALANCEZERO-SCOPE.md`, still the intended scope — the UI/deploy-target changes on 2026-08-10 didn't change *what* the app does, only *how* it's built and shipped.

## In scope
1. Connect a SimpleFIN Access URL (real user only; demo user is pre-seeded, skips this).
2. Scheduled sync of accounts + transactions, respecting the 24/day SimpleFIN rate cap.
3. Transaction list, assignable to categories (manual only — no auto-categorization).
4. Category management (create/edit budget categories).
5. Monthly budget view: allocate available funds to categories until income − allocated = 0.
6. Category balance rollover month to month (the actual zero-based mechanic).
7. Two-user auth (real + demo) with per-user data isolation.

Partially built already: auth (needs the token-auth rework), data model, budget routes (need converting from server-rendered to JSON API), basic UI (being replaced by the React SPA). Not yet started: SimpleFIN connection flow, scheduled sync job, EKS deploy.

## Explicitly deferred, not MVP
Auto-categorization rules, multi-account households, budget templates/goals, reports beyond the current month, public signup.

## Known local gotcha
Heredoc pastes (`cat > file <<'EOF' ... EOF`) containing `<...>` have silently dropped that content before in this project (hit twice on a Flask route decorator with a dynamic segment, e.g. `@app.route("/records/<int:record_id>")` landed as `@app.route("/records/")`, no error). Verify any pasted file containing angle brackets with `grep` immediately after writing it, especially API routes with path parameters.
