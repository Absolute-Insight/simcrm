import { test, expect } from '@playwright/test'
import { createDoc, deleteDoc, getList } from '../helpers'

/**
 * The planner is where "plans linked to actual activity" is authored. The two
 * properties worth protecting end to end are that a planned item survives a
 * reload (it is a record, not local state) and that proposing a week writes
 * nothing until the rep confirms — the Phase 8 write gate applied to planning.
 */

interface PlanRow {
	name: string
}

async function deleteOwnPlans(request: Parameters<typeof getList>[0]) {
	const plans = await getList<PlanRow>(request, 'CRM Rep Plan', {
		filters: { user: 'Administrator' },
		fields: ['name'],
		limit: 50,
	})
	for (const plan of plans) {
		await deleteDoc(request, 'CRM Rep Plan', plan.name)
	}
}

test.describe('Planner', () => {
	test.beforeEach(async ({ request, page }) => {
		await deleteOwnPlans(request)
		await page.goto('/crm/planner')
		await expect(page.getByRole('heading', { name: 'Planner' })).toBeVisible()
	})

	test.afterEach(async ({ request }) => {
		await deleteOwnPlans(request)
	})

	test('a planned activity survives a reload', async ({ page }) => {
		await page
			.getByRole('button', { name: /add activity/i })
			.first()
			.click()

		const dialog = page.getByRole('dialog')
		await expect(dialog).toBeVisible()
		await dialog.getByLabel('Note').fill('E2E planned call')
		await dialog.getByRole('button', { name: /add to plan/i }).click()

		await expect(page.getByText('E2E planned call')).toBeVisible()

		await page.getByRole('button', { name: /save plan/i }).click()
		await expect(page.getByText(/plan saved/i)).toBeVisible()

		await page.reload()
		await expect(page.getByText('E2E planned call')).toBeVisible()
	})

	test('proposing a week writes nothing until the rep saves', async ({
		page,
		request,
	}) => {
		await page.getByRole('button', { name: /propose my week/i }).click()

		// whatever the proposal produced — items or a "nothing to plan" notice —
		// no plan record may exist before an explicit save
		await page.waitForTimeout(500)
		const plans = await getList<PlanRow>(request, 'CRM Rep Plan', {
			filters: { user: 'Administrator' },
			fields: ['name'],
			limit: 5,
		})
		expect(plans).toHaveLength(0)
	})

	test('unsaved work is not silently discarded when the week changes', async ({
		page,
	}) => {
		await page
			.getByRole('button', { name: /add activity/i })
			.first()
			.click()

		const dialog = page.getByRole('dialog')
		await dialog.getByLabel('Note').fill('E2E unsaved item')
		await dialog.getByRole('button', { name: /add to plan/i }).click()
		await expect(page.getByText('E2E unsaved item')).toBeVisible()

		page.once('dialog', (confirmation) => confirmation.dismiss())
		await page.getByRole('button', { name: /next week/i }).click()

		// the discard was refused, so the item and its week must both still be here
		await expect(page.getByText('E2E unsaved item')).toBeVisible()
	})
})

test.describe('Planner seeded from records', () => {
	let orgName: string

	test.beforeAll(async ({ request }) => {
		const org = await createDoc<{ name: string }>(
			request,
			'CRM Organization',
			{ organization_name: `E2E Planner Org ${Date.now()}` },
		)
		orgName = org.name
	})

	test.afterAll(async ({ request }) => {
		if (orgName) await deleteDoc(request, 'CRM Organization', orgName)
	})

	test('an item linked to a deal shows the record, not its primary key', async ({
		page,
		request,
	}) => {
		const deal = await createDoc<{ name: string }>(request, 'CRM Deal', {
			organization: orgName,
			deal_owner: 'Administrator',
		})
		const monday = new Date()
		monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7))
		const weekStart = monday.toISOString().slice(0, 10)

		const plan = await createDoc<{ name: string }>(request, 'CRM Rep Plan', {
			user: 'Administrator',
			week_start: weekStart,
			items: [
				{
					activity_type: 'Call',
					planned_date: weekStart,
					note: 'E2E linked call',
					reference_doctype: 'CRM Deal',
					reference_docname: deal.name,
				},
			],
		})

		await page.goto('/crm/planner')
		await expect(page.getByText('E2E linked call')).toBeVisible()
		// the card names the organization, never the autoincrement docname
		await expect(page.getByText(deal.name, { exact: true })).toHaveCount(0)

		await deleteDoc(request, 'CRM Rep Plan', plan.name)
		await deleteDoc(request, 'CRM Deal', deal.name)
	})
})
