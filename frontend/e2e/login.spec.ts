import { test, expect } from '@playwright/test'

test('redirects to /login from /', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.locator('form')).toBeVisible()
})

test('shows error on invalid credentials', async ({ page }) => {
  await page.goto('/login')
  await page.fill('#username', 'wronguser')
  await page.fill('#password', 'wrongpass')
  await page.click('button[type="submit"]')
  await expect(page.locator('[role="alert"]')).toBeVisible()
  await expect(page.locator('[role="alert"]')).toContainText('Invalid credentials')
})

test('logs in with valid credentials', async ({ page }) => {
  await page.goto('/login')
  await page.fill('#username', 'salesman_a')
  await page.fill('#password', 'salesman_a')
  await page.click('button[type="submit"]')
  // After successful login, should navigate away from /login
  await expect(page).not.toHaveURL(/\/login/)
})
