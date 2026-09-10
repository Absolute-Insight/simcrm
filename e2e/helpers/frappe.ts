import * as fs from 'fs'
import { test, type APIRequestContext } from '@playwright/test'
import { csrfFile, roleOfAuthFile, type Role } from '../roles'

/**
 * Frappe API response wrapper.
 */
export interface FrappeResponse<T = unknown> {
	message?: T
	exc?: string
	exc_type?: string
	_server_messages?: string
}

/**
 * CSRF tokens, one per session.
 *
 * Frappe binds the token to the sid, so a request context carrying the rep's
 * cookies has to send the rep's token. Each role project's setup writes its
 * own `e2e/.auth/<role>.csrf.json`; the token for the project's default
 * `request` fixture is read from the file matching the project's storageState,
 * and a context built by hand (the `admin` fixture) registers its token here.
 */
const registeredTokens = new WeakMap<APIRequestContext, string>()
const fileTokens = new Map<string, string>()

export function registerCsrfToken(request: APIRequestContext, token: string) {
	registeredTokens.set(request, token)
}

/** The token auth.setup.ts saved for a role; '' when that setup did not run. */
export function readCsrfToken(role: Role): string {
	const file = csrfFile(role)
	const cached = fileTokens.get(file)
	if (cached !== undefined) return cached

	let token = ''
	try {
		if (fs.existsSync(file)) {
			token = JSON.parse(fs.readFileSync(file, 'utf-8')).csrf_token || ''
		}
	} catch (error) {
		console.warn(`Failed to read CSRF token file ${file}:`, error)
	}
	fileTokens.set(file, token)
	return token
}

function csrfTokenFor(request: APIRequestContext): string {
	const registered = registeredTokens.get(request)
	if (registered !== undefined) return registered

	let role: Role | null = null
	try {
		role = roleOfAuthFile(test.info().project.use.storageState)
	} catch {
		// outside a test (a global setup, a script): fall through to admin
	}
	return readCsrfToken(role || 'admin')
}

function jsonHeaders(request: APIRequestContext): Record<string, string> {
	const csrfToken = csrfTokenFor(request)
	return {
		'Content-Type': 'application/json',
		...(csrfToken ? { 'X-Frappe-CSRF-Token': csrfToken } : {}),
	}
}

/**
 * Create a document via the Frappe REST API.
 */
export async function createDoc<T = Record<string, unknown>>(
	request: APIRequestContext,
	doctype: string,
	doc: Record<string, unknown>,
): Promise<T> {
	const response = await request.post(`/api/resource/${doctype}`, {
		data: doc,
		headers: jsonHeaders(request),
	})

	if (!response.ok()) {
		throw new Error(`Failed to create ${doctype}: ${await response.text()}`)
	}

	const result = await response.json()
	return result.data as T
}

/**
 * Get a document by name via the Frappe REST API.
 */
export async function getDoc<T = Record<string, unknown>>(
	request: APIRequestContext,
	doctype: string,
	name: string,
): Promise<T> {
	const response = await request.get(
		`/api/resource/${doctype}/${encodeURIComponent(name)}`,
	)

	if (!response.ok()) {
		throw new Error(
			`Failed to get ${doctype}/${name}: ${await response.text()}`,
		)
	}

	const result = await response.json()
	return result.data as T
}

/**
 * Delete a document via the Frappe REST API.
 */
export async function deleteDoc(
	request: APIRequestContext,
	doctype: string,
	name: string,
): Promise<void> {
	const response = await request.delete(
		`/api/resource/${doctype}/${encodeURIComponent(name)}`,
		{ headers: jsonHeaders(request) },
	)

	if (!response.ok()) {
		throw new Error(
			`Failed to delete ${doctype}/${name}: ${await response.text()}`,
		)
	}
}

/**
 * Call a Frappe whitelisted method.
 */
export async function callMethod<T = unknown>(
	request: APIRequestContext,
	method: string,
	args: Record<string, unknown> = {},
): Promise<T> {
	const response = await request.post(`/api/method/${method}`, {
		data: args,
		headers: jsonHeaders(request),
	})

	if (!response.ok()) {
		throw new Error(`Failed to call ${method}: ${await response.text()}`)
	}

	const result: FrappeResponse<T> = await response.json()
	return result.message as T
}

/**
 * Get a list of documents via the Frappe REST API.
 */
export async function getList<T = Record<string, unknown>>(
	request: APIRequestContext,
	doctype: string,
	options: {
		fields?: string[]
		filters?: Record<string, unknown>
		limit?: number
		orderBy?: string
	} = {},
): Promise<T[]> {
	const params = new URLSearchParams()

	if (options.fields) params.set('fields', JSON.stringify(options.fields))
	if (options.filters) params.set('filters', JSON.stringify(options.filters))
	if (options.limit) params.set('limit_page_length', options.limit.toString())
	if (options.orderBy) params.set('order_by', options.orderBy)

	const response = await request.get(
		`/api/resource/${doctype}?${params.toString()}`,
	)

	if (!response.ok()) {
		throw new Error(
			`Failed to get list of ${doctype}: ${await response.text()}`,
		)
	}

	const result = await response.json()
	return result.data as T[]
}

/**
 * The Monday of the week the *site* considers current, from a server timestamp.
 *
 * Deriving the week from the runner's clock is the trap `Planner.vue` documents
 * avoiding: it takes `today` from the site timezone precisely because the
 * browser's zone lands in the wrong week around the Sunday/Monday boundary. A
 * test that computes its own week from `new Date()` writes a plan into one week
 * and asserts against another — silently correct six days out of seven, red on
 * the seventh. Measured here: the runner is UTC while the site runs IST, so
 * every Sunday after 18:30 UTC the two disagree about which week it is.
 *
 * Two sources were tried and rejected. `window.timezone` is injected by the
 * Frappe server's boot, so it is absent when the suite runs against the vite
 * dev origin. `System Settings.time_zone` reads back empty on a site that never
 * set one, which silently falls through to the runner's clock — a fix that
 * looks right and does nothing.
 *
 * A freshly created document's `creation` is the site's own clock, which is the
 * same one `frappe.utils.getdate()` answers with. Pass any server timestamp.
 */
export function mondayOfServerDate(serverDatetime: string): string {
	// "2026-08-17 11:49:05.467652" — parsed as local parts, never through Date's
	// UTC handling, which would shift the day back across the boundary this
	// helper exists to get right.
	const [datePart] = serverDatetime.split(' ')
	const [year, month, day] = datePart.split('-').map(Number)
	const date = new Date(year, month - 1, day)
	date.setDate(date.getDate() - ((date.getDay() + 6) % 7))

	const pad = (n: number) => String(n).padStart(2, '0')
	return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}
