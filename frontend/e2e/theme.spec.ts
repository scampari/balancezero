import { test, expect } from '@playwright/test'

// Each Playwright test gets a fresh context (localStorage included), but be
// explicit so a stored theme can never bleed into another spec if that ever
// changes.
test.beforeEach(async ({ page }) => {
  await page.goto('/login')
  await page.evaluate(() => localStorage.clear())
})

test.describe('theme picker', () => {
  test('the header exposes a Theme control', async ({ page }) => {
    await page.goto('/login')
    // The picker only renders inside AppShell (authed pages); the login page
    // still gets a themed <html>. Verify the default resolved theme is applied.
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toMatch(/^(dark|light)$/)
  })

  test('choosing Light sets data-theme and survives a reload', async ({ page }) => {
    // Arrange — log in so the header picker is present
    await page.goto('/login')
    await page.getByLabel('Username').fill('sam')
    await page.getByLabel('Password').fill('correct horse battery staple')
    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page).toHaveURL(/\/budget$/)

    // Act
    await page.getByLabel('Theme').selectOption('light')

    // Assert — applied now
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe('light')

    // Assert — persisted across a real reload (pre-paint script reads storage)
    await page.reload()
    await expect(page).toHaveURL(/\/budget$/)
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe('light')
    await expect(page.getByLabel('Theme')).toHaveValue('light')
  })

  test('System follows the OS colour scheme', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' })
    await page.goto('/login')
    await page.getByLabel('Username').fill('sam')
    await page.getByLabel('Password').fill('correct horse battery staple')
    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page).toHaveURL(/\/budget$/)

    // Default choice is "System"
    await expect(page.getByLabel('Theme')).toHaveValue('system')
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe('dark')

    // Flip the OS scheme — "System" tracks it live
    await page.emulateMedia({ colorScheme: 'light' })
    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.theme))
      .toBe('light')
  })
})
