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

    // Assert — real data from the real API, not hardcoded. Amount assertion
    // updated for the UI redesign's real currency formatting (-$42.50, was
    // the raw API string "-42.50") — a deliberate behavior change, not a
    // contract break: the underlying value is unchanged, only its display.
    await expect(page.getByText('E2E Grocery Run')).toBeVisible()
    await expect(page.getByText('-$42.50')).toBeVisible()
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

  test('a transaction can go To Be Budgeted and back to Uncategorized', async ({ page }) => {
    await login(page)
    await page.getByRole('link', { name: 'Transactions' }).click()
    const select = page.getByRole('row', { name: /E2E Grocery Run/ }).getByRole('combobox')

    await select.selectOption({ label: 'To Be Budgeted' })
    await expect(async () => {
      expect(await selectedOptionText(select)).toBe('To Be Budgeted')
    }).toPass()

    // The bug: this used to be a no-op.
    await select.selectOption({ label: 'Uncategorized' })
    await expect(async () => {
      expect(await selectedOptionText(select)).toBe('Uncategorized')
    }).toPass()

    await page.getByRole('link', { name: 'Budget' }).click()
    await page.getByRole('link', { name: 'Transactions' }).click()
    const revisited = page.getByRole('row', { name: /E2E Grocery Run/ }).getByRole('combobox')
    expect(await selectedOptionText(revisited)).toBe('Uncategorized')
  })

  test('a transaction can be added manually and deleted', async ({ page }) => {
    await login(page)
    await page.getByRole('link', { name: 'Transactions' }).click()

    await page.getByRole('button', { name: 'Add transaction' }).click()
    await page.getByLabel('Amount').fill('-13.37')
    await page.getByLabel('Description').fill('Manual Coffee')
    await page.getByRole('button', { name: 'Add', exact: true }).click()

    const row = page.getByRole('row', { name: /Manual Coffee/ })
    await expect(row).toBeVisible()
    await expect(row.getByText('-$13.37')).toBeVisible()

    // Delete it
    await row.getByRole('button', { name: 'Delete Manual Coffee' }).click()
    await expect(page.getByText('Manual Coffee')).toHaveCount(0)

    // Still gone after a round-trip
    await page.getByRole('link', { name: 'Budget' }).click()
    await page.getByRole('link', { name: 'Transactions' }).click()
    await expect(page.getByText('Manual Coffee')).toHaveCount(0)
  })
})
