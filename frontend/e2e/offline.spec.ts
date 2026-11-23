import { test, expect } from '@playwright/test'

/**
 * Phase 7 offline gate: an order taken with no connection is queued on the
 * device, surfaced in the pending badge, and sent once on reconnect without a
 * duplicate. Requires the seeded stack (`make up && make seed`).
 */
test('an offline order queues, shows pending and syncs on reconnect', async ({ page, context }) => {
  await page.goto('/login')
  await page.fill('#username', 'salesman_a')
  await page.fill('#password', 'salesman_a')
  await page.click('button[type="submit"]')
  await expect(page).not.toHaveURL(/\/login/)

  await page.getByRole('link', { name: 'New order' }).click()
  await page.getByRole('button', { name: 'Retailer A' }).click()
  await expect(page.getByLabel('Murukku 200 g quantity')).toBeVisible()

  await context.setOffline(true)
  await page.getByLabel('Murukku 200 g quantity').fill('2')
  await page.getByRole('button', { name: 'Submit order' }).click()

  await expect(page.getByRole('status')).toContainText('saved on this device')
  await expect(page.getByText('Pending (1)')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sync now' })).toBeVisible()

  // Reconnecting flushes the outbox automatically; the badge clears.
  await context.setOffline(false)
  await expect(page.getByText(/^Pending \(/)).toHaveCount(0, { timeout: 15_000 })
  await page.getByRole('link', { name: 'My orders' }).click()
  await expect(page.getByText(/Murukku 200 g × 2\.000/)).toBeVisible()
})
