import { test, expect } from '../../fixtures'
import { createDoc, deleteDoc, getDoc, getList } from '../../helpers'
import { ROLE_ACCOUNTS } from '../../roles'
import type { Page } from '@playwright/test'

/**
 * Accepting a suggestion as the rep it was raised for -- the core proactive
 * write path, run past the confirm dialog. The store does two writes that
 * cannot share a transaction (frappe.client.insert of the task, then
 * crm.api.suggestions.accept), and the badge on the sidebar is a third
 * resource reloaded afterwards. Each of the three is asserted: the task exists
 * exactly once with the confirmed title, the suggestion is Accepted, and the
 * open count the rep sees drops by one.
 */
interface Named {
	name: string
}

const rep = ROLE_ACCOUNTS.rep.user
const TITLE = 'E2E rep: this deal has gone quiet'
const TASK_TITLE = 'E2E rep follow up'

/** The card for the seeded suggestion, not whichever card happens to be first. */
function card(page: Page) {
	return page
		.locator('div')
		.filter({ has: page.getByRole('link', { name: new RegExp(TITLE) }) })
		.last()
}

/** The sidebar toggle. Its accessible name carries the open count. */
function inboxButton(page: Page) {
	return page.getByRole('button', { name: /^Suggestions/ })
}

/** "Suggestions (3 open)" -> 3; "Suggestions" -> 0. */
async function openCount(page: Page): Promise<number> {
	const label = (await inboxButton(page).getAttribute('aria-label')) || ''
	expect(label).not.toMatch(/unavailable/)
	const match = /\((\d+) open\)/.exec(label)
	return match ? Number(match[1]) : 0
}

test.describe('Rep suggestion inbox', () => {
	let orgName: string
	let dealName: string
	let suggestionName: string

	test.beforeEach(async ({ admin }) => {
		const org = await createDoc<Named>(admin, 'CRM Organization', {
			organization_name: `E2E Rep Suggest Org ${Date.now()}`,
		})
		orgName = org.name

		const deal = await createDoc<Named>(admin, 'CRM Deal', {
			organization: orgName,
			deal_owner: rep,
			expected_deal_value: 1000,
			expected_closure_date: '2026-12-31',
		})
		dealName = deal.name

		const suggestion = await createDoc<Named>(admin, 'CRM Suggestion', {
			signal: 'idle_deal',
			title: TITLE,
			rationale: 'No activity logged in 21 days.',
			reference_doctype: 'CRM Deal',
			reference_docname: dealName,
			user: rep,
			suggested_action: 'create_task',
			action_payload: JSON.stringify({ title: TASK_TITLE }),
			status: 'Open',
			score: 80,
		})
		suggestionName = suggestion.name
	})

	test.afterEach(async ({ admin }) => {
		const tasks = await getList<Named>(admin, 'CRM Task', {
			filters: { reference_doctype: 'CRM Deal', reference_docname: dealName },
			fields: ['name'],
		}).catch(() => [] as Named[])
		for (const task of tasks) {
			await deleteDoc(admin, 'CRM Task', task.name).catch(() => {})
		}
		for (const [doctype, name] of [
			['CRM Suggestion', suggestionName],
			['CRM Deal', dealName],
			['CRM Organization', orgName],
		] as const) {
			if (name) await deleteDoc(admin, doctype, name).catch(() => {})
		}
	})

	test('accepting creates the task once, closes the suggestion and drops the badge', async ({
		page,
		request,
	}) => {
		await page.goto('/crm')
		await expect(inboxButton(page)).toBeVisible()
		// the count has loaded once the seeded row is in it
		await expect
			.poll(() => openCount(page), { message: 'badge counts the seeded suggestion' })
			.toBeGreaterThanOrEqual(1)
		const before = await openCount(page)

		await inboxButton(page).click()
		await expect(page.getByText(TITLE)).toBeVisible()
		await card(page).getByRole('button', { name: 'Create task' }).click()

		// the confirm dialog shows exactly what will be written
		const dialog = page.getByRole('dialog')
		await expect(dialog).toBeVisible()
		await expect(dialog.getByRole('textbox').first()).toHaveValue(TASK_TITLE)
		await dialog.getByRole('button', { name: 'Create task' }).click()

		await expect(dialog).toBeHidden()
		await expect(page.getByText(TITLE)).toHaveCount(0)
		await expect.poll(() => openCount(page)).toBe(before - 1)

		// the rep's own session can read both records back
		const tasks = await getList<{ name: string; title: string; status: string }>(
			request,
			'CRM Task',
			{
				filters: { reference_doctype: 'CRM Deal', reference_docname: dealName },
				fields: ['name', 'title', 'status'],
			},
		)
		expect(tasks).toHaveLength(1)
		expect(tasks[0].title).toBe(TASK_TITLE)
		expect(tasks[0].status).toBe('Todo')

		const suggestion = await getDoc<{ status: string }>(
			request,
			'CRM Suggestion',
			suggestionName,
		)
		expect(suggestion.status).toBe('Accepted')
	})
})
