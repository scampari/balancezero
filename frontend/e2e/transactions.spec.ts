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

// The per-row category control is a datalist-backed <input> (role combobox),
// not a <select> — pick by typing the exact label and blurring to commit.
function categoryField(page: Page, descriptionRe: RegExp): Locator {
  return page.getByRole('row', { name: descriptionRe }).getByRole('combobox')
}

async function pickCategory(field: Locator, label: string): Promise<void> {
  await field.fill(label)
  await field.blur()
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
    // Description + amount render in both the desktop table and the mobile
    // card list; assert the first (desktop) match.
    await expect(page.getByText('E2E Grocery Run').first()).toBeVisible()
    await expect(page.getByText('-$42.50').first()).toBeVisible()
  })

  test('a transfer transaction shows a Transfer badge', async ({ page }) => {
    await login(page)
    await page.getByRole('link', { name: 'Transactions' }).click()

    const row = page.getByRole('row', { name: /E2E Transfer To Savings/ })
    await expect(row.getByText('Transfer')).toBeVisible()
  })

  test('changing category persists', async ({ page }) => {
    // Arrange
    await login(page)
    await page.getByRole('link', { name: 'Transactions' }).click()

    // Act
    await pickCategory(categoryField(page, /E2E Grocery Run/), 'Groceries')

    // Assert — UI updates without a page reload
    await expect(categoryField(page, /E2E Grocery Run/)).toHaveValue('Groceries')

    // Assert — actually persisted server-side, not just local UI state.
    // Navigate away and back via the app's own links (not a browser reload —
    // the access token is deliberately memory-only, so a real reload
    // legitimately loses the session, which is a separate, accepted tradeoff).
    await page.getByRole('link', { name: 'Budget' }).click()
    await expect(page).toHaveURL(/\/budget$/)
    await page.getByRole('link', { name: 'Transactions' }).click()
    await expect(categoryField(page, /E2E Grocery Run/)).toHaveValue('Groceries')
  })

  test('a transaction can go To Be Budgeted and back to Uncategorized', async ({ page }) => {
    await login(page)
    await page.getByRole('link', { name: 'Transactions' }).click()

    await pickCategory(categoryField(page, /E2E Grocery Run/), 'To Be Budgeted')
    await expect(categoryField(page, /E2E Grocery Run/)).toHaveValue('To Be Budgeted')

    // The bug: this used to be a no-op.
    await pickCategory(categoryField(page, /E2E Grocery Run/), 'Uncategorized')
    await expect(categoryField(page, /E2E Grocery Run/)).toHaveValue('Uncategorized')

    await page.getByRole('link', { name: 'Budget' }).click()
    await page.getByRole('link', { name: 'Transactions' }).click()
    await expect(categoryField(page, /E2E Grocery Run/)).toHaveValue('Uncategorized')
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

  test('a new transaction is auto-categorized from a prior same-merchant choice', async ({ page }) => {
    await login(page)
    await page.getByRole('link', { name: 'Transactions' }).click()

    // First one: category it explicitly.
    await page.getByRole('button', { name: 'Add transaction' }).click()
    await page.getByLabel('Amount').fill('-6.00')
    await page.getByLabel('Description').fill('AUTOCAT DELI')
    // The add form's category <select> (the per-row pickers are datalist inputs).
    await page.locator('form select[name="category_id"]').selectOption({ label: 'Groceries' })
    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(page.getByRole('row', { name: /AUTOCAT DELI/ }).first()).toBeVisible()

    // Second one at the same merchant, no category picked.
    await page.getByRole('button', { name: 'Add transaction' }).click()
    await page.getByLabel('Amount').fill('-7.25')
    await page.getByLabel('Description').fill('AUTOCAT DELI')
    await page.getByRole('button', { name: 'Add', exact: true }).click()

    // Both rows now show Groceries — the second inherited the first's choice.
    const rows = page.getByRole('row', { name: /AUTOCAT DELI/ })
    await expect(rows).toHaveCount(2)
    await expect(rows.nth(0).getByRole('combobox')).toHaveValue('Groceries')
    await expect(rows.nth(1).getByRole('combobox')).toHaveValue('Groceries')
  })
})
