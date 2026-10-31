import { test, expect } from '@playwright/test'

/**
 * The reports page is the "clean, informative reporting" surface. What matters
 * is that the registry drives it (switching a report re-renders the columns the
 * backend declared), that the date range is on offer, and that the CSV a user
 * downloads is the report they are looking at.
 */
test.describe('Reports', () => {
	test.beforeEach(async ({ page }) => {
		await page.goto('/crm/reports')
		await expect(page.getByRole('tablist', { name: 'Reports' })).toBeVisible()
	})

	test('the report registry drives the page', async ({ page }) => {
		for (const title of [
			'Pipeline by stage',
			'Funnel conversion',
			'Plan adherence by rep',
			'Forecast vs actual',
			'Quota attainment by rep',
		]) {
			await expect(page.getByRole('tab', { name: title })).toBeVisible()
		}

		// The description is the registry speaking, and unlike a column header it
		// is present whether or not the period happens to contain any rows.
		await page.getByRole('tab', { name: 'Funnel conversion' }).click()
		await expect(page.getByText(/lead-to-won conversion/i)).toBeVisible()

		await page.getByRole('tab', { name: 'Plan adherence by rep' }).click()
		await expect(page.getByText(/planned activities due in the period/i)).toBeVisible()
		await expect(page.getByText(/lead-to-won conversion/i)).toHaveCount(0)
	})

	test('the selected report is deep-linkable', async ({ page }) => {
		await page.getByRole('tab', { name: 'Funnel conversion' }).click()
		await expect(page).toHaveURL(/report=funnel_conversion/)

		await page.reload()
		await expect(
			page.getByRole('tab', { name: 'Funnel conversion' }),
		).toHaveAttribute('aria-selected', 'true')
	})

	test('reports offer the date range', async ({ page }) => {
		// pipeline_by_stage counts deals created in the period, so it has the
		// picker too; it used to be a snapshot without one
		await page.getByRole('tab', { name: 'Pipeline by stage' }).click()
		await expect(page.getByText(/open deals created in the period/i)).toBeVisible()
		await expect(page.getByPlaceholder('Period')).toHaveValue(/ to /)

		await page.getByRole('tab', { name: 'Funnel conversion' }).click()
		await expect(page.getByRole('button', { name: /last .* days/i })).toBeVisible()
		// beside the presets, the dates themselves -- MBP's managers could not
		// find the custom range when it hid behind the preset menu
		await expect(page.getByPlaceholder('Period')).toHaveValue(/ to /)
	})

	test('exports the report on screen as CSV', async ({ page }) => {
		await page.getByRole('tab', { name: 'Funnel conversion' }).click()
		await expect(
			page.getByRole('columnheader', { name: /conversion/i }),
		).toBeVisible()

		const downloadPromise = page.waitForEvent('download')
		await page.getByRole('button', { name: 'Export CSV' }).click()
		const download = await downloadPromise

		expect(download.suggestedFilename()).toContain('funnel_conversion')
		expect(download.suggestedFilename()).toMatch(/\.csv$/)
	})
})
