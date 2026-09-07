import type { Page } from '@playwright/test'

/**
 * What a session must not produce while a page renders: an uncaught exception,
 * or an API call the server refused. A rep hitting a `403` on first load is the
 * failure the role projects exist to catch -- a component rendered for a user
 * whose permissions it never checked -- and the client surfaces it as a toast
 * that no locator can name reliably. The network is the honest witness.
 */
export interface RenderFailures {
	pageErrors: string[]
	refusedRequests: string[]
}

export function watchRenderFailures(page: Page): RenderFailures {
	const failures: RenderFailures = { pageErrors: [], refusedRequests: [] }

	page.on('pageerror', (error) => failures.pageErrors.push(error.message))
	page.on('response', (response) => {
		const url = response.url()
		if (!url.includes('/api/')) return
		if (response.status() === 403 || response.status() >= 500) {
			failures.refusedRequests.push(`${response.status()} ${url}`)
		}
	})

	return failures
}
