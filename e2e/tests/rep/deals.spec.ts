import { test, expect } from '../../fixtures'
import { createDoc, deleteDoc, getList } from '../../helpers'
import { ROLE_ACCOUNTS } from '../../roles'

/**
 * A rep sees their own deals and nobody else's. The rule lives in
 * crm.permissions.org_hierarchy (permission_query_conditions on CRM Deal) and
 * is tested server-side; this checks the list the rep actually opens honours
 * it, and that the generic document API -- the other door -- does too.
 *
 * The records are seeded as Administrator: the rep may not create a deal for
 * somebody else, which is rather the point.
 */
interface Named {
	name: string
}

const rep = ROLE_ACCOUNTS.rep.user
const stamp = Date.now()
const OWN_ORG = `E2E Rep Own Org ${stamp}`
const OTHER_ORG = `E2E Rep Other Org ${stamp}`

test.describe('Rep deal list', () => {
	const created: Array<[string, string]> = []
	let ownDeal: string
	let otherDeal: string

	test.beforeAll(async ({ admin }) => {
		for (const [orgName, owner] of [
			[OWN_ORG, rep],
			[OTHER_ORG, 'Administrator'],
		] as const) {
			const org = await createDoc<Named>(admin, 'CRM Organization', {
				organization_name: orgName,
			})
			created.unshift(['CRM Organization', org.name])
			const deal = await createDoc<Named>(admin, 'CRM Deal', {
				organization: org.name,
				deal_owner: owner,
				// mandatory on a site with forecasting enabled, harmless elsewhere
				expected_deal_value: 1000,
				expected_closure_date: '2026-12-31',
			})
			created.unshift(['CRM Deal', deal.name])
			if (owner === rep) ownDeal = deal.name
			else otherDeal = deal.name
		}
	})

	test.afterAll(async ({ admin }) => {
		// deals before organizations: `created` was built newest-first
		for (const [doctype, name] of created) {
			await deleteDoc(admin, doctype, name).catch(() => {})
		}
	})

	test('the list shows the rep their own deal and not another owner\'s', async ({
		page,
	}) => {
		await page.goto('/crm/deals')

		await expect(page.getByText(OWN_ORG).first()).toBeVisible()
		await expect(page.getByText(OTHER_ORG)).toHaveCount(0)
	})

	test('the document API applies the same scope', async ({ request }) => {
		const visible = await getList<Named>(request, 'CRM Deal', {
			filters: { name: ['in', [ownDeal, otherDeal]] },
			fields: ['name'],
		})
		expect(visible.map((row) => row.name)).toEqual([ownDeal])

		const direct = await request.get(
			`/api/resource/CRM Deal/${encodeURIComponent(otherDeal)}`,
		)
		expect(direct.status()).toBe(403)
	})
})
