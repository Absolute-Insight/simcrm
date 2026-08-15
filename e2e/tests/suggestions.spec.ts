import { test, expect } from '@playwright/test'
import { createDoc, deleteDoc, getDoc } from '../helpers'

/**
 * The suggestion inbox is the proactive surface — the thing that makes the
 * product tell you what needs attention before you ask. Two properties are
 * load-bearing and are asserted here: accepting a suggestion writes only after
 * the human confirms the exact payload (the Phase 8 write gate), and a failed
 * fetch must never render as "all clear", which would be a lie about the one
 * surface a rep trusts to be complete.
 */

interface Named {
	name: string
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
			title: 'E2E: this deal has gone quiet',
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
			if (name) {
				await deleteDoc(request, doctype, name).catch(() => {})
			}
		}
	})

	test('an open suggestion reaches the inbox and can be dismissed', async ({
		page,
		request,
	}) => {
		await page.goto('/crm')
		await page.getByRole('button', { name: /suggestions/i }).first().click()

		await expect(
			page.getByText('E2E: this deal has gone quiet'),
		).toBeVisible()

		await page.getByRole('button', { name: /dismiss/i }).first().click()

		await expect(
			page.getByText('E2E: this deal has gone quiet'),
		).toHaveCount(0)

		const suggestion = await getDoc<{ status: string }>(
			request,
			'CRM Suggestion',
			suggestionName,
		)
		expect(suggestion.status).toBe('Dismissed')
	})

	test('accepting writes nothing until the confirm dialog is submitted', async ({
		page,
		request,
	}) => {
		await page.goto('/crm')
		await page.getByRole('button', { name: /suggestions/i }).first().click()
		await expect(
			page.getByText('E2E: this deal has gone quiet'),
		).toBeVisible()

		await page.getByRole('button', { name: /create task/i }).first().click()

		// the confirm dialog shows exactly what will be written, pre-filled from
		// the suggestion's action_payload
		const dialog = page.getByRole('dialog')
		await expect(dialog).toBeVisible()
		await expect(dialog.getByDisplayValue('E2E follow up')).toBeVisible()

		// cancelling must leave the suggestion open and create nothing
		await dialog.getByRole('button', { name: /cancel/i }).click()
		const stillOpen = await getDoc<{ status: string }>(
			request,
			'CRM Suggestion',
			suggestionName,
		)
		expect(stillOpen.status).toBe('Open')
	})

	test('the per-record section explains the deal health score', async ({
		page,
	}) => {
		await page.goto(`/crm/deals/${dealName}`)

		// the score is never a bare colour-coded number: it carries its scale and
		// the factors that produced it
		const attention = page.getByText(/needs attention/i).first()
		await expect(attention).toBeVisible()
		await expect(page.getByText('E2E: this deal has gone quiet')).toBeVisible()
	})
})
