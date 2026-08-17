import { Page, expect } from '@playwright/test'

/**
 * Frappe's standard login page. After a successful login with
 * redirect-to=/crm the browser lands on the CRM SPA.
 */
export class LoginPage {
	constructor(private page: Page) {}

	async goto() {
		await this.page.goto('/login?redirect-to=/crm')
		await this.page.waitForLoadState('networkidle')
	}

	/**
	 * Frappe's login markup carries several submit buttons (password, email link,
	 * 2FA), so the button is located through the form that owns the password field
	 * rather than by class — the class has already changed once (btn-login ->
	 * es-button) and broke every UI login test when it did.
	 */
	private submitButton() {
		return this.page.locator('form:has(#login_password) button[type="submit"]')
	}

	async login(email = 'Administrator', password = 'admin') {
		await this.goto()
		await this.page.fill('#login_email', email)
		await this.page.fill('#login_password', password)

		// Watch the login call. Without this a rejected credential, a CSRF
		// failure and a slow redirect all end at the same navigation timeout,
		// which says only that we did not arrive -- never why.
		const loggedIn = this.page.waitForResponse(
			(response) =>
				response.url().includes('/api/method/login') &&
				response.request().method() === 'POST',
			{ timeout: 30000 },
		)
		await this.submitButton().click()

		const response = await loggedIn
		if (!response.ok()) {
			const detail = (await response.text().catch(() => '')).slice(0, 500)
			throw new Error(`Login failed: HTTP ${response.status()} — ${detail}`)
		}
		// Match the *path*, not the URL string. CI serves the site at
		// http://crm.test:8000, and /\/crm/ matches the '//crm' in that host --
		// so this returned instantly while still on the login page and the
		// caller then looked for app chrome that was not there. Locally, on
		// localhost:8080, the same regex is accidentally correct, which is why
		// it only ever failed in CI.
		await this.page.waitForURL((url) => url.pathname.startsWith('/crm'), {
			timeout: 30000,
		})
	}

	async submitCredentials(email: string, password: string) {
		await this.page.fill('#login_email', email)
		await this.page.fill('#login_password', password)
		await this.submitButton().click()
	}

	async expectOnLoginPage() {
		await expect(this.page).toHaveURL(/.*login.*/)
	}
}
