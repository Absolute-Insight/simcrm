import { test, expect } from '../../fixtures'
import { watchRenderFailures } from '../../helpers'

/**
 * The rep's first screen. router.js sends anyone without the Sales Manager
 * role from /crm to the planner -- "what am I doing Tuesday" must not need a
 * route learned on day one -- and that screen has to render for a plain Sales
 * User without a single refused API call. Administrator never exercises this
 * branch: it is a manager everywhere the router looks.
 */
test.describe('Rep home', () => {
	test('the rep lands on the planner, and nothing on it is refused', async ({
		page,
	}) => {
		const failures = watchRenderFailures(page)

		await page.goto('/crm')

		await expect(page).toHaveURL((url) => url.pathname === '/crm/planner')
		await expect(page.getByRole('button', { name: 'Propose my week' })).toBeVisible()
		// the sidebar is the rep's map of the app; it has to be there too
		await expect(page.getByRole('link', { name: 'Deals' }).first()).toBeVisible()
		await page.waitForLoadState('networkidle')

		expect(failures.pageErrors).toEqual([])
		expect(failures.refusedRequests).toEqual([])
	})
})
