import { execSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { type Page, expect, test } from '@playwright/test'
import { seedEnv } from './env'

// Covers spec/frontend-app.md § "Overspend notification + Cover dialog"
// (changes/030). The API behind the Cover button is POST /api/allocations/move
// in spec/budget-api.md.

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PASSWORD = 'correct horse battery staple'
const USERNAME = 'sam-overspend'
const CLEAN_USERNAME = 'sam-overspend-clean'

// Re-seeded before every test, not once per file: these tests move money, so
// each needs the overspent state back. The script is idempotent by design.
// Args set the overspend and the source's balance — the pre-fill and
// insufficient-source cases state their own setups (see the seed's docstring).
function seed(overspend?: string, dining?: string) {
  const repoRoot = path.resolve(__dirname, '../..')
  const args = [overspend, dining].filter(Boolean).join(' ')
  execSync(`venv/bin/python3 seed_e2e_overspend.py ${args}`.trim(), {
    cwd: repoRoot,
    stdio: 'inherit',
    env: seedEnv(),
  })
}

test.beforeEach(() => seed())

async function login(page: Page, username = USERNAME) {
  await page.goto('/login')
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page).toHaveURL(/\/budget$/)
}

const row = (page: Page, name: string) => page.locator(`li[data-category="${name}"]`)
const banner = (page: Page) => page.locator('[data-overspend-banner]')
const coverButton = (page: Page, name: string) => page.getByRole('button', { name: `Cover ${name}` })
const dialog = (page: Page) => page.getByRole('dialog', { name: /cover/i })
const sourcePicker = (page: Page) => dialog(page).getByLabel('Cover from')
const amountInput = (page: Page) => dialog(page).getByLabel('Amount to move')
const submit = (page: Page) => dialog(page).getByRole('button', { name: 'Move money' })
const readyToAssign = (page: Page) => page.locator('[data-ready-to-assign]')

/** A category row's "available" figure, as displayed. */
const available = (page: Page, name: string) => row(page, name).locator('[data-available]')

test.describe('budget page — overspend notification + cover', () => {
  test('the banner appears and names each overspent envelope', async ({ page }) => {
    await login(page)

    // The banner is an alert region above the category table, saying how many
    // envelopes are overspent.
    await expect(banner(page)).toBeVisible()
    await expect(banner(page)).toContainText('1')
    await expect(banner(page)).toContainText('Groceries')
    await expect(banner(page)).toContainText('40.00')
    await expect(coverButton(page, 'Groceries')).toBeVisible()
  })

  test('no banner appears when nothing is overspent', async ({ page }) => {
    await login(page, CLEAN_USERNAME)

    // Same categories, same spending — Groceries is just funded enough to
    // cover it, so there is nothing to alert about.
    await expect(row(page, 'Groceries')).toBeVisible()
    await expect(banner(page)).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^Cover / })).toHaveCount(0)

    // Positive control: the same page does show a banner for a user who *is*
    // overspent. Without this the assertions above would pass simply because
    // no banner exists anywhere on the page yet — an absence is only evidence
    // once presence is possible.
    await page.context().clearCookies()
    await login(page, USERNAME)
    await expect(banner(page)).toBeVisible()
  })

  test('covering from another envelope clears the banner', async ({ page }) => {
    await login(page)
    const assignableBefore = await readyToAssign(page).textContent()

    await coverButton(page, 'Groceries').click()
    await sourcePicker(page).selectOption({ label: 'Dining' })
    await submit(page).click()

    // The dialog closes and the alert goes with it.
    await expect(dialog(page)).toBeHidden()
    await expect(banner(page)).toHaveCount(0)

    // Groceries is brought to zero; Dining paid for it.
    await expect(available(page, 'Groceries')).toHaveText('$0.00')
    await expect(available(page, 'Dining')).toHaveText('$60.00')

    // A move is zero-sum across allocations, so the unassigned pool is untouched.
    await expect(readyToAssign(page)).toHaveText(assignableBefore ?? '')

    // Surviving a reload proves it was persisted, not just local state.
    await page.reload()
    await expect(available(page, 'Groceries')).toHaveText('$0.00')
    await expect(available(page, 'Dining')).toHaveText('$60.00')
    await expect(banner(page)).toHaveCount(0)
  })

  test('covering from Ready to Assign draws on the unassigned pool', async ({ page }) => {
    await login(page)
    await expect(readyToAssign(page)).toHaveText('$100.00')

    await coverButton(page, 'Groceries').click()
    // Ready to Assign is the default source — accept it as-is.
    await submit(page).click()

    await expect(dialog(page)).toBeHidden()
    await expect(banner(page)).toHaveCount(0)
    await expect(available(page, 'Groceries')).toHaveText('$0.00')
    await expect(readyToAssign(page)).toHaveText('$60.00')

    // Only Groceries moved — Dining is untouched.
    await expect(available(page, 'Dining')).toHaveText('$100.00')
  })

  test('the dialog pre-fills the amount needed to reach zero', async ({ page }) => {
    seed('37.50')
    await login(page)

    await coverButton(page, 'Groceries').click()

    // Exactly the shortfall, not a round number and not blank.
    await expect(amountInput(page)).toHaveValue('37.50')
    // The destination is fixed from this entry point — you are covering
    // Groceries, that is what the button said.
    await expect(dialog(page)).toContainText('Groceries')
  })

  test('covering from a source that does not hold enough is rejected and writes nothing', async ({
    page,
  }) => {
    seed('40.00', '10.00')
    await login(page)

    await coverButton(page, 'Groceries').click()
    await sourcePicker(page).selectOption({ label: 'Dining' })
    await amountInput(page).fill('40.00')
    await submit(page).click()

    // The dialog stays open and says why.
    await expect(dialog(page)).toBeVisible()
    await expect(dialog(page).getByRole('alert')).toBeVisible()

    // Nothing on the page moved, and nothing was written — the backend
    // rejects before touching either row, so a reload shows the same state.
    await expect(banner(page)).toBeVisible()
    await page.reload()
    await expect(available(page, 'Groceries')).toHaveText('-$40.00')
    await expect(available(page, 'Dining')).toHaveText('$10.00')
    await expect(banner(page)).toBeVisible()
  })
})
