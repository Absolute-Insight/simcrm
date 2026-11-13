import { test, expect } from '../../fixtures'
import type { APIRequestContext } from '@playwright/test'
import { deleteDoc, getDoc, getList, uniqueSuffix, watchRenderFailures } from '../../helpers'
import { ROLE_ACCOUNTS } from '../../roles'

/**
 * Field mode on a phone, as the rep: the surface that has to keep working at
 * a site with no reception.
 *
 * What can be driven here is everything short of the cold start. The cached
 * shell needs a service worker, and CI's origin is plain http on a hostname,
 * which is not a secure context, so no worker registers there. The capture
 * path does not need one: the page is already open when the network goes, the
 * entry is stored on the device, and it is sent when the network returns --
 * once. That is the part a rep's working day depends on, and it runs for real.
 */

interface PlanRow {
	name: string
	items?: { note?: string; outcome?: string }[]
}

const rep = ROLE_ACCOUNTS.rep.user

/** The rep's plans with their items: a child row is only readable through its parent. */
async function repPlans(admin: APIRequestContext): Promise<PlanRow[]> {
	const names = await getList<PlanRow>(admin, 'CRM Rep Plan', {
		filters: { user: rep },
		fields: ['name'],
		limit: 20,
	})
	return Promise.all(names.map((plan) => getDoc<PlanRow>(admin, 'CRM Rep Plan', plan.name)))
}

test.describe('Field mode @smoke', () => {
	const note = `E2E field ${uniqueSuffix()}`

	test.afterEach(async ({ admin }) => {
		// Only a plan this spec alone wrote into is removed: on a seeded dev
		// site the rep has a week of their own, and that is not ours to delete.
		for (const plan of await repPlans(admin)) {
			const items = plan.items ?? []
			if (items.length && items.every((item) => (item.note || '').startsWith('E2E field'))) {
				await deleteDoc(admin, 'CRM Rep Plan', plan.name).catch(() => {})
			}
		}
	})

	test('the week, the customers and the tasks open from the copy on the device', async ({
		page,
	}) => {
		const failures = watchRenderFailures(page)

		await page.goto('/crm/field')
		await expect(page.getByRole('heading', { name: 'My week' })).toBeVisible()
		await expect(page.getByRole('button', { name: 'Log activity' })).toBeVisible()
		await expect(page.getByRole('tablist')).toBeVisible()

		await page.getByRole('link', { name: 'Customers' }).click()
		await expect(page.getByPlaceholder('Search customers')).toBeVisible()

		await page.getByRole('link', { name: 'Tasks' }).click()
		await expect(page.getByRole('button', { name: 'New task' })).toBeVisible()

		const overflow = await page.evaluate(
			() => document.documentElement.scrollWidth - window.innerWidth,
		)
		expect(overflow).toBeLessThanOrEqual(0)
		expect(failures.pageErrors).toEqual([])
		expect(failures.refusedRequests).toEqual([])
	})

	test('an activity logged with no network is kept, shown, and sent once when it returns', async ({
		page,
		context,
	}) => {
		const replays: string[] = []
		page.on('request', (request) => {
			if (request.url().includes('crm.api.offline.replay')) {
				replays.push(JSON.parse(request.postData() || '{}').request_id)
			}
		})

		await page.goto('/crm/field')
		await expect(page.getByRole('button', { name: 'Log activity' })).toBeVisible()

		await context.setOffline(true)
		await expect(page.getByText('Offline', { exact: true })).toBeVisible()

		await page.getByRole('button', { name: 'Log activity' }).click()
		const dialog = page.getByRole('dialog')
		await dialog.getByRole('combobox').first().click()
		await page.getByRole('option', { name: 'Admin', exact: true }).click()
		await dialog.locator('textarea').fill(note)
		await dialog.getByRole('button', { name: 'Log activity' }).click()

		// on the device and on the screen, with nothing sent
		await expect(page.getByText(note)).toBeVisible()
		await expect(page.getByText('Waiting to send')).toBeVisible()
		await expect(page.getByRole('link', { name: /waiting to be sent/ })).toBeVisible()
		expect(replays).toEqual([])

		await context.setOffline(false)

		// sent, confirmed by a fresh copy, and no longer marked as waiting
		await expect(page.getByRole('link', { name: /waiting to be sent/ })).toBeHidden({
			timeout: 20000,
		})
		await expect(page.getByText('Waiting to send')).toBeHidden()
		await expect(page.getByText(note)).toBeVisible()
		expect(new Set(replays).size).toBe(1)
	})

	test('what was logged is on the server exactly once', async ({ page, admin }) => {
		await page.goto('/crm/field')
		await page.getByRole('button', { name: 'Log activity' }).click()
		const dialog = page.getByRole('dialog')
		await dialog.getByRole('combobox').first().click()
		await page.getByRole('option', { name: 'Admin', exact: true }).click()
		const once = `${note} once`
		await dialog.locator('textarea').fill(once)
		await dialog.getByRole('button', { name: 'Log activity' }).click()
		await expect(page.getByText(once)).toBeVisible()
		await expect(page.getByText('Waiting to send')).toBeHidden({ timeout: 20000 })

		const rows = (await repPlans(admin))
			.flatMap((plan) => plan.items ?? [])
			.filter((item) => item.note === once)
		expect(rows).toHaveLength(1)
	})
})
