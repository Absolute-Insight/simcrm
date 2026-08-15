import { test, expect, type Page } from '@playwright/test'
import { createDoc, deleteDoc, getDoc } from '../helpers'

/**
 * The suggestion inbox is the proactive surface — the thing that tells a rep
 * what needs attention before they ask. Two properties are load-bearing and are
 * asserted here: accepting writes only after the human confirms the exact
 * payload (the Phase 8 write gate), and dismissing collects a reason, because
 * the signal engine reads those reasons to stretch a repeat dismisser's
 * cooldown.
 *
 * Every locator is scoped to the seeded card. The panel shows the whole open
 * queue, which on a working site is hundreds of rows, so a `.first()` here
 * would act on somebody else's suggestion.
 */

interface Named {
	name: string
}

const TITLE = 'E2E: this deal has gone quiet'

/** The card for the seeded suggestion, not whichever card happens to be first. */
function card(page: Page) {
	return page
		.locator('div')
		.filter({ has: page.getByRole('link', { name: new RegExp(TITLE) }) })
		.last()
}

async function openInbox(page: Page) {
	await page.goto('/crm')
	await page.getByRole('button', { name: 'Suggestions' }).click()
	await expect(page.getByText(TITLE)).toBeVisible()
}

test.describe('Suggestion inbox', () => {
	let orgName: string
	let dealName: string
	let suggestionName: string

	test.beforeEach(async ({ request }) => {
		const org = await createDoc<Named>(request, 'CRM Organization', {
			organization_name: `E2E Suggest Org ${Date.now()}`,
		})
		orgName = org.name

		const deal = await createDoc<Named>(request, 'CRM Deal', {
			organization: orgName,
			deal_owner: 'Administrator',
		})
		dealName = deal.name

		const suggestion = await createDoc<Named>(request, 'CRM Suggestion', {
			signal: 'idle_deal',
			title: TITLE,
			rationale: 'No activity logged in 21 days.',
			reference_doctype: 'CRM Deal',
			reference_docname: dealName,
			user: 'Administrator',
			suggested_action: 'create_task',
			action_payload: JSON.stringify({ title: 'E2E follow up' }),
			status: 'Open',
			score: 80,
		})
		suggestionName = suggestion.name
	})

	test.afterEach(async ({ request }) => {
		for (const [doctype, name] of [
			['CRM Suggestion', suggestionName],
			['CRM Deal', dealName],
			['CRM Organization', orgName],
		] as const) {
			if (name) await deleteDoc(request, doctype, name).catch(() => {})
		}
	})

	test('an open suggestion reaches the inbox and is dismissed with a reason', async ({
		page,
		request,
	}) => {
		await openInbox(page)

		await card(page).getByRole('button', { name: 'Dismiss' }).click()

		// the reason is not optional: the engine reads it back to tune thresholds
		const dialog = page.getByRole('dialog')
		await expect(dialog).toBeVisible()
		await dialog.getByRole('button', { name: 'Dismiss' }).click()

		await expect(page.getByText(TITLE)).toHaveCount(0)

		const suggestion = await getDoc<{ status: string; dismiss_reason: string }>(
			request,
			'CRM Suggestion',
			suggestionName,
		)
		expect(suggestion.status).toBe('Dismissed')
		expect(suggestion.dismiss_reason).toBeTruthy()
	})

	test('accepting writes nothing until the confirm dialog is submitted', async ({
		page,
		request,
	}) => {
		await openInbox(page)

		await card(page).getByRole('button', { name: 'Create task' }).click()

		// the confirm dialog shows exactly what will be written, pre-filled from
		// the suggestion's action_payload
		const dialog = page.getByRole('dialog')
		await expect(dialog).toBeVisible()
		await expect(dialog.getByRole('textbox').first()).toHaveValue(
			'E2E follow up',
		)

		// cancelling must leave the suggestion open and create nothing
		await dialog.getByRole('button', { name: 'Cancel' }).click()
		await expect(dialog).toBeHidden()

		const stillOpen = await getDoc<{ status: string }>(
			request,
			'CRM Suggestion',
			suggestionName,
		)
		expect(stillOpen.status).toBe('Open')
	})

	test('the record page carries the same suggestion', async ({ page }) => {
		await page.goto(`/crm/deals/${dealName}`)
		await expect(page.getByText(TITLE)).toBeVisible()
	})
})
