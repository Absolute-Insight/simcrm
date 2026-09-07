import { test, expect } from '../../fixtures'
import { watchRenderFailures } from '../../helpers'

/**
 * The Sales Manager's landing and dashboard. Managers keep the views-driven
 * default rather than the planner redirect, and the dashboard renders the
 * team controls (the rep filter) that are hidden from a rep -- rendered by a
 * Sales Manager who is not System Manager, which is the branch Administrator
 * never takes.
 */
test.describe('Manager dashboard', () => {
	test('the manager is not sent to the planner', async ({ page }) => {
		await page.goto('/crm')
		await expect(page).toHaveURL((url) => url.pathname.startsWith('/crm'))
		await expect(page).not.toHaveURL((url) => url.pathname === '/crm/planner')
		await expect(page.getByRole('link', { name: 'Deals' }).first()).toBeVisible()
	})

	test('the dashboard renders the team view without a refused call', async ({
		page,
	}) => {
		const failures = watchRenderFailures(page)

		await page.goto('/crm/dashboard')

		// the rep filter exists only for managers and admins
		await expect(page.getByPlaceholder('Sales User')).toBeVisible()
		await expect(page.getByRole('button', { name: 'Refresh' })).toBeVisible()
		await page.waitForLoadState('networkidle')

		expect(failures.pageErrors).toEqual([])
		expect(failures.refusedRequests).toEqual([])
	})
})
