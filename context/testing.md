# Testing

No test framework existed in this project before `changes/001-api-spa-rewrite/`. Established during that change's test-planning:

- **Backend**: pytest. Standard Flask test client for integration tests.
- **Database in tests**: real Postgres via Docker, never SQLite — even though SQLite is allowed for local dev convenience. Tests must catch schema/constraint/type behavior that only shows up on the real production database type. Reuses the Docker setup already planned for deployment, rather than adding a second, different local-only test setup.
- **Mock boundary default**: real dependencies (DB) wherever controlled; mock only at the HTTP client layer for uncontrolled external services with no safe test environment (e.g. SimpleFIN — no sandbox exists, per `context/simplefin-integration.md`, so its adapter tests will mock at the HTTP layer once that slice starts).
