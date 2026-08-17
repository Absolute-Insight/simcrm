import { test, expect, type APIRequestContext } from '@playwright/test'
import { createDoc, deleteDoc, getList, mondayOfServerDate } from '../helpers'

/**
 * The planner is where "plans linked to actual activity" is authored. Three
 * properties are worth protecting end to end: a planned item is a record and
 * survives a reload, proposing a week writes nothing until the rep confirms
 * (the Phase 8 write gate applied to planning), and unsaved work is not thrown
 * away silently when the week changes.
 */

interface PlanRow {
	name: string
}

async function deleteOwnPlans(request: APIRequestContext) {
	const plans = await getList<PlanRow>(request, 'CRM Rep Plan', {
		filters: { user: 'Administrator' },
		fields: ['name'],
		limit: 50,
	})
	for (const plan of plans) {
		await deleteDoc(request, 'CRM Rep Plan', plan.name).catch(() => {})
	}
}

test.describe('Planner', () => {
	test.beforeEach(async ({ request, page }) => {
		await deleteOwnPlans(request)
		await page.goto('/crm/planner')
		await expect(page.getByRole('button', { name: 'Propose my week' })).toBeVisible()
	})

	test.afterEach(async ({ request }) => {
		await deleteOwnPlans(request)
	})

	test('a planned activity survives a reload', async ({ page }) => {
		await page.getByRole('button', { name: 'Add an activity' }).first().click()

		const dialog = page.getByRole('dialog')
		await expect(dialog).toBeVisible()
		await dialog.getByPlaceholder('Note').fill('E2E planned call')
		await dialog.getByRole('button', { name: /add to plan/i }).click()

		await expect(page.getByText('E2E planned call')).toBeVisible()

		await page.getByRole('button', { name: 'Save plan' }).click()
		await expect(page.getByText('E2E planned call')).toBeVisible()

		await page.reload()
		await expect(page.getByText('E2E planned call')).toBeVisible()
	})

	test('proposing a week writes nothing until the rep saves', async ({
		page,
		request,
	}) => {
		await page.getByRole('button', { name: 'Propose my week' }).click()

		// whatever the proposal produced — items, or a "nothing to plan" notice —
		// no plan record may exist before an explicit save
		await expect(page.getByRole('button', { name: 'Propose my week' })).toBeEnabled()
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
		await page.getByRole('button', { name: 'Add an activity' }).first().click()

		const dialog = page.getByRole('dialog')
		await dialog.getByPlaceholder('Note').fill('E2E unsaved item')
		await dialog.getByRole('button', { name: /add to plan/i }).click()
		await expect(page.getByText('E2E unsaved item')).toBeVisible()

		// refuse the discard prompt — the item and its week must both survive
		page.once('dialog', (confirmation) => confirmation.dismiss())
		await page.getByRole('button', { name: 'Next week' }).click()

		await expect(page.getByText('E2E unsaved item')).toBeVisible()
	})
})

test.describe('Planner items name their record', () => {
	let orgName: string

	test.beforeAll(async ({ request }) => {
		const org = await createDoc<{ name: string }>(request, 'CRM Organization', {
			organization_name: `E2E Planner Org ${Date.now()}`,
		})
		orgName = org.name
	})

	test.afterAll(async ({ request }) => {
		if (orgName) await deleteDoc(request, 'CRM Organization', orgName).catch(() => {})
	})

	test('an item linked to a deal shows the organization, not the primary key', async ({
		page,
		request,
	}) => {
		const deal = await createDoc<{ name: string; creation: string }>(request, 'CRM Deal', {
			organization: orgName,
			deal_owner: 'Administrator',
		})
		// the deal was just created by the site, so its creation stamp is the
		// site's own clock — the one the planner's current week is derived from
		const weekStart = mondayOfServerDate(deal.creation)

		await deleteOwnPlans(request)
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
		await expect(page.getByText(orgName, { exact: false }).first()).toBeVisible()
		// the card names the organization, never the autoincrement docname
		await expect(page.getByText(deal.name, { exact: true })).toHaveCount(0)

		await deleteDoc(request, 'CRM Rep Plan', plan.name).catch(() => {})
		await deleteDoc(request, 'CRM Deal', deal.name).catch(() => {})
	})
})
