import { test, expect } from '@playwright/test'

/**
 * The reports page is the "clean, informative reporting" surface. What matters
 * here is that the registry drives the page (switching a report re-renders the
 * columns the backend declared), that a period-independent report does not show
 * a date picker that changes nothing, and that the CSV the user downloads is the
 * report they are looking at.
 */
test.describe('Reports', () => {
	test.beforeEach(async ({ page }) => {
		await page.goto('/crm/reports')
		await expect(page.getByRole('heading', { name: 'Reports' })).toBeVisible()
	})

	test('the report registry drives the page', async ({ page }) => {
		// every built-in report is listed
		for (const title of [
			'Pipeline by stage',
			'Funnel conversion',
			'Plan adherence by rep',
			'Forecast vs actual',
			'Quota attainment by rep',
		]) {
			await expect(page.getByRole('button', { name: title })).toBeVisible()
		}

		await page.getByRole('button', { name: 'Funnel conversion' }).click()
		await expect(
			page.getByRole('columnheader', { name: /conversion/i }),
		).toBeVisible()

		await page.getByRole('button', { name: 'Plan adherence by rep' }).click()
		await expect(
			page.getByRole('columnheader', { name: /adherence/i }),
		).toBeVisible()
		await expect(
			page.getByRole('columnheader', { name: /conversion/i }),
		).toHaveCount(0)
	})

	test('a period-independent report hides the date picker', async ({
		page,
	}) => {
		// pipeline_by_stage is a snapshot of the open pipeline right now, so a
		// range picker on it would be a control that changes nothing
		await page.getByRole('button', { name: 'Pipeline by stage' }).click()
		await expect(page.getByPlaceholder('Date range')).toHaveCount(0)

		await page.getByRole('button', { name: 'Funnel conversion' }).click()
		await expect(page.getByPlaceholder('Date range')).toBeVisible()
	})

	test('exports the report on screen as CSV', async ({ page }) => {
		await page.getByRole('button', { name: 'Funnel conversion' }).click()

		const download = await Promise.race([
			page.waitForEvent('download'),
			page
				.getByRole('button', { name: 'Export CSV' })
				.click()
				.then(() => page.waitForEvent('download')),
		])

		expect(download.suggestedFilename()).toContain('funnel_conversion')
		expect(download.suggestedFilename()).toMatch(/\.csv$/)
	})
})
