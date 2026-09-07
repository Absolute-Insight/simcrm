import { test as base, type APIRequestContext } from '@playwright/test'
import { authFile, type Role } from './roles'
import { readCsrfToken, registerCsrfToken } from './helpers/frappe'

/**
 * Shared fixtures.
 *
 * `role` is a project-level option: playwright.config.ts sets it per project
 * and auth.setup.ts reads it to know whom to log in as. Specs rarely need it.
 *
 * `admin` is an API context authenticated as Administrator whatever the
 * project's own session is. Role specs use it to seed the records their user
 * must (or must not) see, and to clean up records the user is not allowed to
 * delete. It carries the Administrator CSRF token, so the helpers in
 * ./helpers/frappe.ts can write through it.
 */
export const test = base.extend<{ role: Role; admin: APIRequestContext }>({
	role: ['admin', { option: true }],

	admin: async ({ playwright, baseURL }, use) => {
		const context = await playwright.request.newContext({
			baseURL,
			storageState: authFile('admin'),
		})
		registerCsrfToken(context, readCsrfToken('admin'))
		await use(context)
		await context.dispose()
	},
})

export { expect } from '@playwright/test'
