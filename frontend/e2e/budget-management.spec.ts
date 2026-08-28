import { execSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { type Page, expect, test } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const USERNAME = 'sam-budget'
const PASSWORD = 'correct horse battery staple'

test.beforeAll(() => {
  const repoRoot = path.resolve(__dirname, '../..')
  execSync('venv/bin/python3 seed_e2e_budget.py', {
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

const row = (page: Page, name: string) => page.locator(`li[data-category="${name}"]`)
const archivedRow = (page: Page, name: string) => page.locator(`li[data-archived-category="${name}"]`)
const topLevelNames = (page: Page) =>
  page.locator('ul > li[data-category]:not(.pl-10)').evaluateAll((els) =>
    els.map((el) => el.querySelector('span')?.textContent?.trim() ?? ''),
  )

test.describe('budget page — management', () => {
  test('shows a totals row and the seeded hierarchy', async ({ page }) => {
    await login(page)

    await expect(page.getByText('Available to Spend', { exact: false })).toBeVisible()
    const totals = page.getByTestId('budget-totals')
    await expect(totals).toBeVisible()
    await expect(totals).toContainText('Total')
    // Groceries: allocated 400, spent 55.25 this month → available 344.75
    await expect(totals).toContainText('$344.75')
    // "Groceries" is seeded as a subcategory of "Food"
    await expect(row(page, 'Groceries')).toHaveClass(/pl-10/)
  })

  test('renaming a category persists across navigation', async ({ page }) => {
    await login(page)
    await row(page, 'Dining Out').getByRole('button', { name: 'Rename' }).click()
    const input = row(page, 'Dining Out').getByLabel('Rename Dining Out')
    await input.fill('Restaurants')
    await input.press('Enter')

    await expect(row(page, 'Restaurants')).toBeVisible()
    await expect(row(page, 'Dining Out')).toHaveCount(0)

    await page.getByRole('link', { name: 'Transactions' }).click()
    await expect(page).toHaveURL(/\/transactions$/)
    await page.getByRole('link', { name: 'Budget' }).click()
    await expect(row(page, 'Restaurants')).toBeVisible()
  })

  test('archiving moves a category to the Archived section and unarchiving restores it', async ({ page }) => {
    await login(page)
    await page.locator('details > summary').click() // expand Archived
    await expect(archivedRow(page, 'Old Subscriptions')).toBeVisible()

    await row(page, 'Rent').getByRole('button', { name: 'Archive' }).click()

    await expect(row(page, 'Rent')).toHaveCount(0)
    await expect(archivedRow(page, 'Rent')).toBeVisible()

    await archivedRow(page, 'Rent').getByRole('button', { name: 'Unarchive' }).click()
    await expect(row(page, 'Rent')).toBeVisible()
  })

  test('reordering moves a top-level category', async ({ page }) => {
    await login(page)
    // Wait for the budget list to render before snapshotting order.
    await expect(row(page, 'Food')).toBeVisible()
    const before = await topLevelNames(page)
    expect(before.length).toBeGreaterThan(1)

    await row(page, before[0]).getByRole('button', { name: `Move ${before[0]} down` }).click()

    await expect.poll(() => topLevelNames(page)).not.toEqual(before)
    const after = await topLevelNames(page)
    expect(after[0]).toBe(before[1])
  })

  test('a top-level category with children is a collapsible group that totals them', async ({ page }) => {
    await login(page)
    const food = row(page, 'Food')

    // No editable assign field on the group; its children's amounts are summed.
    await expect(food.getByLabel('Assign amount for Food')).toHaveCount(0)
    await expect(food).toContainText('$400.00') // budgeted = child Groceries' 400
    await expect(food).toContainText('$344.75') // available = 400 - 55.25 spent

    // Collapsing hides the children…
    await expect(row(page, 'Groceries')).toBeVisible()
    await food.getByRole('button', { name: 'Collapse Food' }).click()
    await expect(row(page, 'Groceries')).toHaveCount(0)

    // …and it sticks across navigation (localStorage).
    await page.getByRole('link', { name: 'Transactions' }).click()
    await page.getByRole('link', { name: 'Budget' }).click()
    await expect(row(page, 'Groceries')).toHaveCount(0)
    await row(page, 'Food').getByRole('button', { name: 'Expand Food' }).click()
    await expect(row(page, 'Groceries')).toBeVisible()
  })
})
