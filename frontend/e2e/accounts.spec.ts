import { execSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { type Page, expect, test } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const USERNAME = 'sam-accounts'
const PASSWORD = 'correct horse battery staple'

test.beforeAll(() => {
  const repoRoot = path.resolve(__dirname, '../..')
  execSync('venv/bin/python3 seed_e2e_accounts.py', {
    cwd: repoRoot,
    stdio: 'inherit',
    env: {
      ...process.env,
      SECRET_KEY: 'e2e-test-secret',
      DATABASE_URL: 'postgresql://balancezero_test:balancezero_test@localhost:55432/balancezero_test',
      PLAID_ENCRYPTION_KEY: 'tD039HeVFX17-RRQiCcp3Cv4NjIjKRPkdKQhAgdW6jQ=',
      PLAID_CLIENT_ID: 'test-placeholder-client-id',
      PLAID_SECRET: 'test-placeholder-secret',
    },
  })
})

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Username').fill(USERNAME)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page).toHaveURL(/\/budget$/)
}

test.describe('accounts page — debt-payoff toggle (changes/029)', () => {
  test('the "paying this off" toggle is credit-only, calls the API, and persists', async ({ page }) => {
    await login(page)
    await page.getByRole('link', { name: 'Accounts' }).click()
    await expect(page).toHaveURL(/\/accounts$/)

    const creditCard = page.locator('[data-account-type="credit"]')
    const checking = page.locator('[data-account-type="depository"]')

    // The control shows on the credit card, never on the checking account.
    const toggle = creditCard.getByRole('switch', { name: /paying this off/i })
    await expect(toggle).toBeVisible()
    await expect(checking.getByRole('switch', { name: /paying this off/i })).toHaveCount(0)

    // Turning it on issues the PATCH and reflects the on-state.
    const patch = page.waitForResponse(
      (r) => /\/api\/accounts\/\d+$/.test(r.url()) && r.request().method() === 'PATCH' && r.ok(),
    )
    await toggle.click()
    await patch
    await expect(toggle).toBeChecked()

    // It survives a reload (read back from GET /api/accounts).
    await page.reload()
    await expect(
      page.locator('[data-account-type="credit"]').getByRole('switch', { name: /paying this off/i }),
    ).toBeChecked()
  })
})
