import { execSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { type Locator, type Page, expect, test } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const USERNAME = 'sam'
const PASSWORD = 'correct horse battery staple'

test.beforeAll(() => {
  const repoRoot = path.resolve(__dirname, '../..')
  execSync('venv/bin/python3 seed_e2e_transactions.py', {
    cwd: repoRoot,
    stdio: 'inherit',
    env: {
      ...process.env,
      SECRET_KEY: 'e2e-test-secret',
      DATABASE_URL: 'postgresql://balancezero_test:balancezero_test@localhost:55432/balancezero_test',
      SIMPLEFIN_ENCRYPTION_KEY: 'tD039HeVFX17-RRQiCcp3Cv4NjIjKRPkdKQhAgdW6jQ=',
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

async function selectedOptionText(select: Locator): Promise<string | null | undefined> {
  return select.evaluate((el: HTMLSelectElement) => el.options[el.selectedIndex]?.textContent)
}

test.describe('transactions page', () => {
  test('shows real seeded transaction data', async ({ page }) => {
    // Arrange
    await login(page)

    // Act — client-side navigation via the app's own link, not page.goto()
    // (a hard navigation would remount the app and lose the in-memory token)
    await page.getByRole('link', { name: 'Transactions' }).click()

    // Assert — real data from the real API, not hardcoded
    await expect(page.getByText('E2E Grocery Run')).toBeVisible()
    await expect(page.getByText('-42.50')).toBeVisible()
  })

  test('changing category persists', async ({ page }) => {
    // Arrange
    await login(page)
    await page.getByRole('link', { name: 'Transactions' }).click()
    const row = page.getByRole('row', { name: /E2E Grocery Run/ })
    const select = row.getByRole('combobox')

    // Act
    await select.selectOption({ label: 'Groceries' })

    // Assert — UI updates without a page reload
    await expect(async () => {
      expect(await selectedOptionText(select)).toBe('Groceries')
    }).toPass()

    // Assert — actually persisted server-side, not just local UI state.
    // Navigate away and back via the app's own links (not a browser reload —
    // the access token is deliberately memory-only, so a real reload
    // legitimately loses the session, which is a separate, accepted tradeoff).
    await page.getByRole('link', { name: 'Budget' }).click()
    await expect(page).toHaveURL(/\/budget$/)
    await page.getByRole('link', { name: 'Transactions' }).click()
    const revisitedSelect = page.getByRole('row', { name: /E2E Grocery Run/ }).getByRole('combobox')
    expect(await selectedOptionText(revisitedSelect)).toBe('Groceries')
  })
})
