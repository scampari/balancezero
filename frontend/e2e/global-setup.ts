import { execSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Runs once before the whole Playwright suite (before webServer starts).
// Ensures the test Postgres container is up, then resets/seeds the schema —
// see ../../seed_e2e.py for what "reset" means.
export default function globalSetup() {
  const repoRoot = path.resolve(__dirname, '../..')

  execSync('docker compose up -d test-db', { cwd: repoRoot, stdio: 'inherit' })
  execSync(
    'until [ "$(docker inspect --format=\'{{.State.Health.Status}}\' balancezero-test-db-1 2>/dev/null)" = "healthy" ]; do sleep 1; done',
    { shell: '/bin/bash', cwd: repoRoot, stdio: 'inherit' }
  )

  execSync('venv/bin/python3 seed_e2e.py', {
    cwd: repoRoot,
    stdio: 'inherit',
    env: {
      ...process.env,
      SECRET_KEY: 'e2e-test-secret',
      DATABASE_URL: 'postgresql://balancezero_test:balancezero_test@localhost:55432/balancezero_test',
      SIMPLEFIN_ENCRYPTION_KEY: 'tD039HeVFX17-RRQiCcp3Cv4NjIjKRPkdKQhAgdW6jQ=',
    },
  })
}
