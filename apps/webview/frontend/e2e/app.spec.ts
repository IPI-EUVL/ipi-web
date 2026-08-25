import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

async function expectNoPageOverflow(page: import('@playwright/test').Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
  expect(overflow).toBe(false)
}

test('live workspace renders real data and accessible stage interactions', async ({ page }, testInfo) => {
  await page.goto('/')
  await expect(page.getByText('System status')).toBeVisible()
  await expect(page.getByRole('group', { name: 'Twelve-position sample stage' })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Sample / })).toHaveCount(12)

  await page.getByRole('button', { name: /^Sample 3,/ }).focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('.slot-details').getByText('Sample 3', { exact: true })).toBeVisible()

  await page.getByRole('tab', { name: 'Cameras' }).click()
  await expect(page.getByText('Camera feeds are not configured.')).toBeVisible()
  await page.getByRole('tab', { name: 'Sample stage' }).click()

  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter((violation) => ['critical', 'serious'].includes(violation.impact ?? ''))).toEqual([])
  await expectNoPageOverflow(page)
  await page.screenshot({ path: `test-results/live-${testInfo.project.name}.png`, fullPage: true })
})

test('navigation preserves functional and placeholder routes', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('link', { name: 'Subsystems' }).click()
  await expect(page.getByRole('heading', { name: 'Subsystems', exact: true })).toBeVisible()
  await expect(page.getByRole('table')).toBeVisible()

  await page.getByRole('link', { name: 'Exposures' }).click()
  await expect(page.getByRole('heading', { name: 'Exposure browser is not implemented yet.' })).toBeVisible()
  await expect(page.getByRole('link', { name: /Grafana/ })).toHaveAttribute('href', 'http://localhost:3000/')
  await expectNoPageOverflow(page)
})