import { test, expect } from '../../fixtures'
import { watchRenderFailures } from '../../helpers'

/**
 * One phone viewport, as the rep (the `mobile` project is Pixel 5). Below
 * 768px the router swaps in the Mobile* pages and the shell drops the desktop
 * sidebar for a different navigation, none of which the desktop projects ever
 * render. This is a smoke: the rep's home loads, the deal list is reachable,
 * and nothing is refused or thrown along the way.
 */
test.describe('Mobile smoke @smoke', () => {
	test('the rep home and the deal list render on a phone', async ({ page }) => {
		const failures = watchRenderFailures(page)

		await page.goto('/crm')
		await expect(page).toHaveURL((url) => url.pathname === '/crm/planner')
		await expect(page.getByRole('button', { name: 'Propose my week' })).toBeVisible()

		await page.goto('/crm/deals')
		await expect(page).toHaveURL((url) => url.pathname.startsWith('/crm/deals'))
		await expect(page.getByRole('link', { name: 'Deals', exact: true }).first()).toBeVisible()
		await page.waitForLoadState('networkidle')

		// the page must fit the viewport: a horizontal scrollbar on a phone is
		// a layout that escaped its container
		const overflow = await page.evaluate(
			() => document.documentElement.scrollWidth - window.innerWidth,
		)
		expect(overflow).toBeLessThanOrEqual(0)

		expect(failures.pageErrors).toEqual([])
		expect(failures.refusedRequests).toEqual([])
	})
})
