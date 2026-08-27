import { execSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { type Page, expect, test } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const USERNAME = 'sam-reports'
const PASSWORD = 'correct horse battery staple'

test.beforeAll(() => {
  const repoRoot = path.resolve(__dirname, '../..')
  execSync('venv/bin/python3 seed_e2e_reports.py', {
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

test.describe('reports page', () => {
  test('renders the panels with real aggregated data', async ({ page }) => {
    await login(page)
    await page.getByRole('link', { name: 'Reports' }).click()
    await expect(page).toHaveURL(/\/reports$/)

    // Panels
    await expect(page.getByRole('heading', { name: 'Spending by month' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Income vs. expense' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Top merchants' })).toBeVisible()

    // Range pickers
    await expect(page.getByLabel('From')).toBeVisible()
    await expect(page.getByLabel('To')).toBeVisible()

    // Seeded merchant + rent category surface as text
    await expect(page.getByText('WHOLE FOODS')).toBeVisible()
    await expect(page.getByText('Rent', { exact: true })).toBeVisible()
  })

  test('changing the range re-fetches', async ({ page }) => {
    await login(page)
    await page.getByRole('link', { name: 'Reports' }).click()

    const monthOverMonthRows = page.locator('table tbody tr')
    await expect(monthOverMonthRows.first()).toBeVisible()
    expect(await monthOverMonthRows.count()).toBeGreaterThan(1)

    // Narrow the window to a single month.
    const to = await page.getByLabel('To').inputValue()
    await page.getByLabel('From').selectOption(to)

    await expect(monthOverMonthRows).toHaveCount(1)
  })
})
