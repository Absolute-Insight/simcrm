import * as fs from 'fs'
import * as path from 'path'
import { expect, type Page } from '@playwright/test'
import { test as setup } from '../fixtures'
import { authFile, csrfFile, ROLE_ACCOUNTS, type RoleAccount } from '../roles'

/**
 * Authentication setup, one run per role project (see playwright.config.ts).
 * Logs in via the Frappe API, captures that session's CSRF token, and saves
 * the storage state for the projects that depend on it.
 *
 * For the rep and manager the account may not exist yet -- CI installs a
 * fresh site -- so it is created first, as Administrator, with the roles the
 * project stands for. An account that already exists (a seeded dev site) is
 * left exactly as it is.
 */
setup('authenticate', async ({ page, role }) => {
	const account = ROLE_ACCOUNTS[role]
	fs.mkdirSync(path.dirname(authFile(role)), { recursive: true })

	if (role !== 'admin') {
		await ensureUser(page, account)
	}

	await login(page, account)

	const userResponse = await page.request.get(
		'/api/method/frappe.auth.get_logged_user',
	)
	expect(userResponse.ok()).toBeTruthy()
	const userData = await userResponse.json()
	expect(userData.message).toBe(account.user)
	console.log(`Authenticated as: ${userData.message} (${role})`)

	const csrfToken = await captureCsrfToken(page)
	fs.writeFileSync(csrfFile(role), JSON.stringify({ csrf_token: csrfToken }))
	await page.context().storageState({ path: authFile(role) })
})

async function login(page: Page, account: RoleAccount) {
	const response = await page.request.post('/api/method/login', {
		form: { usr: account.user, pwd: account.password },
	})
	expect(
		response.ok(),
		`login as ${account.user} failed: ${response.status()}`,
	).toBeTruthy()
}

/**
 * Load the CRM app so the boot injects the token onto window (see
 * crm/www/crm.html). A missing token means later API writes would fail with an
 * opaque 417, so the setup fails loudly instead of proceeding without one.
 */
async function captureCsrfToken(page: Page): Promise<string> {
	await page.goto('/crm')
	await page.waitForLoadState('networkidle')
	const csrfToken = await page.evaluate(() => {
		const w = window as unknown as {
			csrf_token?: string
			frappe?: { csrf_token?: string }
		}
		return w.csrf_token || w.frappe?.csrf_token
	})
	expect(csrfToken).toBeTruthy()
	return csrfToken as string
}

/**
 * Create the account as Administrator when the site does not have it. Uses
 * the page's own request context so the Administrator session is a real
 * browser session with a CSRF token, then logs out so the role login below
 * starts from Guest.
 */
async function ensureUser(page: Page, account: RoleAccount) {
	await login(page, ROLE_ACCOUNTS.admin)

	const existing = await page.request.get(
		`/api/resource/User/${encodeURIComponent(account.user)}`,
	)
	if (existing.status() === 404) {
		const csrfToken = await captureCsrfToken(page)
		const created = await page.request.post('/api/resource/User', {
			headers: {
				'Content-Type': 'application/json',
				'X-Frappe-CSRF-Token': csrfToken,
			},
			data: {
				email: account.user,
				first_name: account.firstName,
				last_name: account.lastName,
				user_type: 'System User',
				send_welcome_email: 0,
				new_password: account.password,
				roles: account.roles.map((role) => ({ role })),
			},
		})
		expect(
			created.ok(),
			`creating ${account.user} failed: ${await created.text()}`,
		).toBeTruthy()
		console.log(`Created ${account.user} with roles ${account.roles.join(', ')}`)
	} else {
		expect(existing.ok(), `looking up ${account.user}: ${existing.status()}`).toBeTruthy()
	}

	await page.request.get('/api/method/logout')
}
