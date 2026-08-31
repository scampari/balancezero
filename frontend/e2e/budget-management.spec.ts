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

// The row's rename / move / archive actions live behind a ⋮ disclosure now.
// Click the visible (desktop) ⋮ to reveal them.
async function openRowMenu(page: Page, name: string) {
  await row(page, name).locator('summary').getByText('⋮').filter({ visible: true }).click()
}

// Top-level rows and their children are siblings in one <ul>; a child's name
// span carries the muted text colour, a top-level's doesn't.
const topLevelNames = (page: Page) =>
  page.locator('ul.divide-y > li[data-category]').evaluateAll((els) =>
    els
      .map((el) => el.querySelector('summary span.truncate'))
      .filter((span): span is Element => span != null && !span.className.includes('text-(--color-text-muted)'))
      .map((span) => span.textContent?.trim() ?? ''),
  )

test.describe('budget page — management', () => {
  test('budget is separated by month — assigning ahead leaves the current month untouched', async ({
    page,
  }) => {
    await login(page)

    const shopping = row(page, 'Shopping')
    const assign = () => shopping.getByLabel('Assign amount for Shopping')

    // Current month — nothing assigned to Shopping in the seed.
    await expect(assign()).toHaveValue(/^0(\.00)?$/)

    // Step forward a month and budget $75 ahead.
    await page.getByRole('button', { name: 'Next month' }).click()
    await expect(page).toHaveURL(/[?&]month=\d{4}-\d{2}/)
    await assign().fill('75')
    await assign().blur()
    await expect(assign()).toHaveValue('75.00')

    // Back to the current month — still zero, and it survives a reload.
    await page.getByRole('button', { name: 'Today' }).click()
    await expect(page).toHaveURL(/\/budget$/)
    await expect(assign()).toHaveValue(/^0(\.00)?$/)
    await page.reload()
    await expect(assign()).toHaveValue(/^0(\.00)?$/)

    // Forward again — the $75 is still parked in next month.
    await page.getByRole('button', { name: 'Next month' }).click()
    await expect(assign()).toHaveValue('75.00')
  })

  test('shows a totals row and the seeded hierarchy', async ({ page }) => {
    await login(page)

    await expect(page.getByTestId('ready-to-assign')).toBeVisible()
    const totals = page.getByTestId('budget-totals')
    await expect(totals).toBeVisible()
    await expect(totals).toContainText('Total')
    // Groceries: allocated 400, spent 55.25 this month → available 344.75
    await expect(totals).toContainText('$344.75')
    // "Groceries" is seeded as a subcategory of "Food" — the group parent
    // carries the collapse caret, the child row is still visible under it.
    await expect(row(page, 'Food').getByRole('button', { name: /(Collapse|Expand) Food/ })).toBeVisible()
    await expect(row(page, 'Groceries')).toBeVisible()
  })

  test('renaming a category persists across navigation', async ({ page }) => {
    await login(page)
    await openRowMenu(page, 'Dining Out')
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
    await page.locator('summary', { hasText: /^Archived/ }).click() // expand Archived
    await expect(archivedRow(page, 'Old Subscriptions')).toBeVisible()

    await openRowMenu(page, 'Rent')
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

    await openRowMenu(page, before[0])
    await row(page, before[0]).getByRole('button', { name: 'Move down', exact: true }).click()

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

  test('a credit-card payment envelope keeps its assign field but not the manage actions', async ({ page }) => {
    await login(page)

    const cardRow = row(page, 'E2E Rewards Card')
    await expect(cardRow).toBeVisible()

    // Still fundable…
    await expect(cardRow.getByLabel('Assign amount for E2E Rewards Card')).toBeVisible()
    // …but not renameable / movable / archivable, and no target.
    await expect(cardRow.getByRole('button', { name: 'Rename' })).toHaveCount(0)
    await expect(cardRow.getByRole('button', { name: 'Archive' })).toHaveCount(0)
    await expect(cardRow.getByRole('button', { name: 'Set target' })).toHaveCount(0)

    // The card-activity line: $30 spent this month, $30 available to pay it.
    await expect(cardRow).toContainText('$30.00 spent this month')
    await expect(cardRow).toContainText('$30.00 available to pay')

    // The "Credit Card Payments" group can't be a parent for a new category.
    await expect(page.getByRole('option', { name: 'Subcategory of Credit Card Payments' })).toHaveCount(0)
  })
})
