/**
 * The environment this suite hands to anything it spawns — the Flask server
 * in playwright.config.ts, and the seed scripts each spec shells out to.
 *
 * This block used to be copy-pasted byte-for-byte into every spec file,
 * global-setup, and the config. Consolidated 2026-09-08 after a secret
 * scanner flagged the tenth copy.
 *
 * `PLAID_ENCRYPTION_KEY` is a fixed, test-only Fernet key. It encrypts
 * nothing but rows in the throwaway test database, which the suite drops and
 * recreates on every run, and it is hardcoded on purpose so the Python
 * (pytest) and TypeScript (Playwright) halves of the harness agree on one
 * value — an encryption key that differed between them would fail to decrypt
 * its own fixtures. It is not a credential for anything real; the real key
 * lives in `.env`, which is gitignored and never committed. Secret scanners
 * flag it on sight, which is why it is worth having in exactly one place with
 * this note attached.
 *
 * `conftest.py` sets the same three values for the pytest suite and cannot
 * import this file — keep the two in sync. `tests/test_plaid_connect.py`
 * checks for these exact placeholder Plaid strings (not mere truthiness) to
 * tell a placeholder apart from a real credential, so don't change them
 * casually.
 */
export const TEST_DATABASE_URL =
  'postgresql://balancezero_test:balancezero_test@localhost:55432/balancezero_test'

export const E2E_ENV = {
  SECRET_KEY: 'e2e-test-secret',
  DATABASE_URL: TEST_DATABASE_URL,
  PLAID_ENCRYPTION_KEY: 'tD039HeVFX17-RRQiCcp3Cv4NjIjKRPkdKQhAgdW6jQ=',
  // Placeholders so app.py can boot (it requires these at import, no default
  // by design) — e2e tests never touch the Plaid endpoints.
  PLAID_CLIENT_ID: 'test-placeholder-client-id',
  PLAID_SECRET: 'test-placeholder-secret',
} as const

/**
 * `E2E_ENV` layered over the current process env — what `execSync` needs when
 * a spec runs a seed script, since those also inherit PATH and friends.
 */
export function seedEnv(): NodeJS.ProcessEnv {
  return { ...process.env, ...E2E_ENV }
}
