import { test, expect } from '@playwright/test'

/**
 * Phase 3 usability gate: a salesman places an order in under 60 seconds.
 * Requires the seeded stack (`make up && make seed`).
 */
test('salesman places an order in under 60 seconds', async ({ page }) => {
  const started = Date.now()

  await page.goto('/login')
  await page.fill('#username', 'salesman_a')
  await page.fill('#password', 'salesman_a')
  await page.click('button[type="submit"]')
  await expect(page).not.toHaveURL(/\/login/)

  await page.getByRole('link', { name: 'New order' }).click()
  await expect(page.getByRole('heading', { name: 'New order' })).toBeVisible()

  await page.getByRole('button', { name: 'Retailer A' }).click()
  await expect(page.getByLabel('Murukku 200 g quantity')).toBeVisible()
  await page.getByLabel('Murukku 200 g quantity').fill('150')

  await page.getByRole('button', { name: 'Submit order' }).click()
  await expect(page.getByRole('status')).toContainText('submitted')

  const elapsed = Date.now() - started
  expect(elapsed).toBeLessThan(60_000)
})

test('admin sees the salesman order in the inbox', async ({ page }) => {
  await page.goto('/login')
  await page.fill('#username', 'admin')
  await page.fill('#password', 'admin')
  await page.click('button[type="submit"]')

  await page.getByRole('link', { name: 'Order inbox' }).click()
  await expect(page.getByRole('heading', { name: 'Order inbox' })).toBeVisible()
  await expect(page.getByText('Retailer A').first()).toBeVisible()
})
