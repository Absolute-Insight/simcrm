/**
 * The three sessions the suite runs as.
 *
 * Administrator bypasses every permission_query_conditions and has_permission
 * hook, so a suite that only ever runs as Administrator never renders the app
 * the way a Sales User or the Sales Manager will see it on day one. Each role
 * here becomes a Playwright project with its own storage state (see
 * playwright.config.ts); `auth.setup.ts` logs each one in once.
 *
 * The rep and manager default to the demo accounts a seeded dev site carries.
 * On a fresh CI site they do not exist, so the setup creates them (as
 * Administrator) with exactly these roles before logging in as them.
 */
export type Role = 'admin' | 'rep' | 'manager'

export interface RoleAccount {
	user: string
	password: string
	/** Frappe roles to grant when the setup has to create the account. */
	roles: string[]
	firstName: string
	lastName: string
}

export const ROLE_ACCOUNTS: Record<Role, RoleAccount> = {
	admin: {
		user: process.env.FRAPPE_USER || 'Administrator',
		password: process.env.FRAPPE_PASSWORD || 'admin',
		roles: [],
		firstName: 'Administrator',
		lastName: '',
	},
	rep: {
		user: process.env.E2E_REP_USER || 'emily.demo@example.com',
		password: process.env.E2E_REP_PASSWORD || 'Demo#2026qa',
		roles: ['Sales User'],
		firstName: 'Emily',
		lastName: 'Chen',
	},
	manager: {
		user: process.env.E2E_MANAGER_USER || 'sarah.demo@example.com',
		password: process.env.E2E_MANAGER_PASSWORD || 'Demo#2026qa',
		roles: ['Sales Manager', 'Sales User'],
		firstName: 'Sarah',
		lastName: 'Connor',
	},
}

/** Storage state (cookies) for a role. Gitignored under e2e/.auth. */
export function authFile(role: Role): string {
	return `e2e/.auth/${role}.json`
}

/**
 * The CSRF token that belongs to that session. Frappe binds the token to the
 * sid, so a request context carrying the rep's cookies must send the rep's
 * token -- one shared csrf.json was only ever right for one role.
 */
export function csrfFile(role: Role): string {
	return `e2e/.auth/${role}.csrf.json`
}

/** The role a storage-state path was written for, or null for anything else. */
export function roleOfAuthFile(storageState: unknown): Role | null {
	if (typeof storageState !== 'string') return null
	const match = /e2e\/\.auth\/(admin|rep|manager)\.json$/.exec(
		storageState.replace(/\\/g, '/'),
	)
	return match ? (match[1] as Role) : null
}
