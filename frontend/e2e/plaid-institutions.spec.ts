import { execSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { type Page, expect, test } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const USERNAME = 'sam-plaid'
const PASSWORD = 'correct horse battery staple'

test.beforeAll(() => {
  const repoRoot = path.resolve(__dirname, '../..')
  execSync('venv/bin/python3 seed_e2e_plaid.py', {
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

test.describe('linked institutions (multi-bank)', () => {
  test('the accounts page lists every linked institution', async ({ page }) => {
    await login(page)
    await page.getByRole('link', { name: 'Accounts' }).click()

    await expect(page.locator('[data-institution="First Platypus Bank"]')).toBeVisible()
    await expect(page.locator('[data-institution="Second Gingham Bank"]')).toBeVisible()
    // Both institutions still connected → the connect action is the
    // "another bank" variant, and it's always available.
    await expect(page.getByRole('button', { name: 'Connect another bank' })).toBeVisible()
  })

  test('removing an institution drops it from the list but keeps its accounts', async ({ page }) => {
    await login(page)
    await page.getByRole('link', { name: 'Accounts' }).click()

    await page
      .locator('[data-institution="First Platypus Bank"]')
      .getByRole('button', { name: 'Remove' })
      .click()

    // Gone from the institutions list…
    await expect(page.getByText('First Platypus Bank', { exact: true })).toHaveCount(0)
    // …but its account card is still there.
    await expect(page.getByText('First Platypus Bank Checking')).toBeVisible()
  })
})
