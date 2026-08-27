import { execSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const INVITE_CODE = 'E2E-INVITE-CODE'
const USERNAME = 'e2e-signup-user'
const PASSWORD = 'a-good-long-password'

test.beforeAll(() => {
  const repoRoot = path.resolve(__dirname, '../..')
  execSync('venv/bin/python3 seed_e2e_signup.py', {
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

test.describe('invite-only signup', () => {
  test('creating an account with a valid invite code lands on the budget page', async ({ page }) => {
    // Arrange
    await page.goto('/signup')

    // Act
    await page.getByLabel('Username').fill(USERNAME)
    await page.getByLabel('Password').fill(PASSWORD)
    await page.getByLabel('Invite code').fill(INVITE_CODE)
    await page.getByRole('button', { name: 'Create account' }).click()

    // Assert — logged straight in, with a starter category tree to work from
    await expect(page).toHaveURL(/\/budget$/)
    await expect(page.getByText('Ready to Assign')).toBeVisible()
    await expect(page.locator('li[data-category="Housing"]')).toBeVisible()
    await expect(page.locator('li[data-category="Groceries"]')).toBeVisible()
  })

  test('a bad invite code shows an inline error and stays on /signup', async ({ page }) => {
    // Arrange
    await page.goto('/signup')

    // Act
    await page.getByLabel('Username').fill('someone-else')
    await page.getByLabel('Password').fill(PASSWORD)
    await page.getByLabel('Invite code').fill('not-a-real-code')
    await page.getByRole('button', { name: 'Create account' }).click()

    // Assert
    await expect(page).toHaveURL(/\/signup$/)
    await expect(page.getByRole('alert')).toBeVisible()
  })

  test('the login page links to signup', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('link', { name: 'Create an account' }).click()
    await expect(page).toHaveURL(/\/signup$/)
  })
})
