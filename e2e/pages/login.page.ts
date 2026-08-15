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
		await this.submitButton().click()
		await this.page.waitForURL(/\/crm/, { timeout: 30000 })
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
