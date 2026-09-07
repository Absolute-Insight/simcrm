import { defineConfig, devices } from '@playwright/test'
import { authFile, type Role } from './e2e/roles'

/**
 * Playwright configuration for Frappe CRM E2E tests.
 *
 * Uses the "setup project" pattern for authentication, once per role:
 * 1. A setup project logs in as one role and saves its storage state to a file
 *    (auth.setup.ts reads the `role` option to know whom to log in as).
 * 2. The projects that stand for that role depend on the setup and reuse the
 *    stored state.
 *
 * Administrator bypasses every permission hook, so the default `chromium`
 * project cannot see the app the way a rep or the manager will. `rep`,
 * `manager` and `mobile` run the specs under e2e/tests/<role>/ as those users;
 * `chromium` runs everything else as Administrator, as before.
 *
 * @see https://playwright.dev/docs/auth
 */
const desktop = devices['Desktop Chrome']

export default defineConfig<{ role: Role }>({
	testDir: './e2e/tests',
	fullyParallel: false, // sequential for Frappe state consistency
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 2 : 0,
	workers: 1, // single worker for Frappe session management
	reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'html',
	timeout: 60000,

	expect: {
		timeout: 10000,
	},

	use: {
		baseURL: process.env.BASE_URL || 'http://crm.test:8000',
		trace: 'on-first-retry',
		video: 'retain-on-failure',
		screenshot: 'only-on-failure',
		actionTimeout: 15000,
		navigationTimeout: 30000,
	},

	projects: [
		{
			name: 'setup',
			testMatch: /auth\.setup\.ts/,
			use: { role: 'admin' },
		},
		{
			// The rep and manager accounts are created by Administrator when the
			// site lacks them, so their setups run after the admin one.
			name: 'setup-rep',
			testMatch: /auth\.setup\.ts/,
			use: { role: 'rep' },
			dependencies: ['setup'],
		},
		{
			name: 'setup-manager',
			testMatch: /auth\.setup\.ts/,
			use: { role: 'manager' },
			dependencies: ['setup'],
		},
		{
			name: 'chromium',
			testIgnore: /\/tests\/(rep|manager|mobile)\//,
			use: {
				...desktop,
				storageState: authFile('admin'),
				role: 'admin',
			},
			dependencies: ['setup'],
		},
		{
			name: 'rep',
			testMatch: /\/tests\/rep\//,
			use: {
				...desktop,
				storageState: authFile('rep'),
				role: 'rep',
			},
			dependencies: ['setup-rep'],
		},
		{
			name: 'manager',
			testMatch: /\/tests\/manager\//,
			use: {
				...desktop,
				storageState: authFile('manager'),
				role: 'manager',
			},
			dependencies: ['setup-manager'],
		},
		{
			// One phone viewport, as the rep: the layout below 768px is a
			// different component tree (Mobile* pages, bottom navigation), and
			// nothing else in the suite renders it.
			name: 'mobile',
			testMatch: /\/tests\/mobile\//,
			use: {
				...devices['Pixel 5'],
				storageState: authFile('rep'),
				role: 'rep',
			},
			dependencies: ['setup-rep'],
		},
	],
})
