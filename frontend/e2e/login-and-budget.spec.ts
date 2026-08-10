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
    await expect(page.getByText('$0.00')).toBeVisible()
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
})
