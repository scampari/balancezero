import { test, expect } from '@playwright/test'

const USERNAME = 'sam'
const PASSWORD = 'correct horse battery staple'

test.describe('login and budget page (walking skeleton)', () => {
  test('logging in with valid credentials shows the real budget page', async ({ page }) => {
    // Arrange
    await page.goto('/login')

    // Act
    await page.getByLabel('Username').fill(USERNAME)
    await page.getByLabel('Password').fill(PASSWORD)
    await page.getByRole('button', { name: 'Log in' }).click()

    // Assert — real data from the real /api/budget response, not hardcoded
    await expect(page).toHaveURL(/\/budget$/)
    await expect(page.getByText('Ready to Assign')).toBeVisible()
    // Targets the hero figure by test id, not by matching "$0.00" text —
    // the redesign's per-category "of $X.XX" allocation text can contain
    // the same substring when a category has $0 allocated, which made this
    // assertion a strict-mode violation (2 matches) depending on seeded
    // data. The underlying ready_to_assign value/behavior is unchanged.
    await expect(page.getByTestId('ready-to-assign')).toHaveText('$0.00')
  })

  test('wrong password shows an error and stays on the login page', async ({ page }) => {
    // Arrange
    await page.goto('/login')

    // Act
    await page.getByLabel('Username').fill(USERNAME)
    await page.getByLabel('Password').fill('wrong-password')
    await page.getByRole('button', { name: 'Log in' }).click()

    // Assert
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByRole('alert')).toBeVisible()
  })

  test('visiting /budget while logged out redirects to /login', async ({ page }) => {
    // Act — fresh browser context per test (Playwright default), no prior login
    await page.goto('/budget')

    // Assert
    await expect(page).toHaveURL(/\/login$/)
  })

  test('access token is never written to localStorage or sessionStorage', async ({ page }) => {
    // Arrange — real login
    await page.goto('/login')
    await page.getByLabel('Username').fill(USERNAME)
    await page.getByLabel('Password').fill(PASSWORD)
    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page).toHaveURL(/\/budget$/)

    // Act
    const storageDump = await page.evaluate(() => ({
      local: { ...localStorage },
      session: { ...sessionStorage },
    }))

    // Assert — nothing JWT-shaped (three base64url segments joined by dots) anywhere
    const allValues = [...Object.values(storageDump.local), ...Object.values(storageDump.session)]
    const looksLikeJwt = (v: string) => /^[\w-]+\.[\w-]+\.[\w-]+$/.test(v)
    expect(allValues.some(looksLikeJwt)).toBe(false)
  })

  test('reloading the page restores the session via the refresh cookie', async ({ page }) => {
    // Arrange — real login
    await page.goto('/login')
    await page.getByLabel('Username').fill(USERNAME)
    await page.getByLabel('Password').fill(PASSWORD)
    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page).toHaveURL(/\/budget$/)

    // Act — a real browser reload, not client-side navigation. This wipes the
    // in-memory access token by design; only the httpOnly refresh cookie survives.
    await page.reload()

    // Assert — stays on /budget with real data, not bounced to /login
    await expect(page).toHaveURL(/\/budget$/)
    await expect(page.getByText('Ready to Assign')).toBeVisible()
  })
})
