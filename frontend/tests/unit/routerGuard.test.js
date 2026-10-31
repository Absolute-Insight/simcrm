import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * The global guard in router.js, run for real: the stores it consults are the
 * app's, over frappe-ui's real createResource, and only the server answers
 * (the resourceFetcher) and the page components are stand-ins.
 */
/* The mocked module is evaluated once per file, so it hands out whichever
   frappe-ui resources module the current tab loaded: their `cache` map is
   module state, and a tab must not inherit the last one's users. */
const fui = vi.hoisted(() => ({ resources: null }))
vi.mock('frappe-ui', async () => {
  const { setConfig, getConfig } = await import(
    '../../node_modules/frappe-ui/src/utils/config.ts'
  )
  return {
    createResource: (...args) => fui.resources.createResource(...args),
    setConfig,
    getConfig,
    call: async () => null,
    toast: { error() {}, success() {} },
  }
})
const page = (name) => ({ default: { name, render: () => null } })
vi.mock('@/pages/Leads.vue', () => page('Leads'))
vi.mock('@/pages/Deals.vue', () => page('Deals'))
vi.mock('@/pages/Contacts.vue', () => page('Contacts'))
vi.mock('@/pages/Organizations.vue', () => page('Organizations'))
vi.mock('@/pages/Planner.vue', () => page('Planner'))
vi.mock('@/pages/Dashboard.vue', () => page('Dashboard'))
vi.mock('@/pages/Tasks.vue', () => page('Tasks'))

const REP = 'rep@example.com'

/**
 * A fresh tab: new stores, a new router, and a server that answers with
 * `respond(url)` (throw to fail the request). Returns the router and the
 * URLs it was asked for.
 */
async function bootTab({ role = 'Sales User', hidden = [], views }) {
  const user = { name: REP, email: REP, full_name: 'Rep', role }
  const requests = []
  vi.resetModules()
  fui.resources = await import(
    '../../node_modules/frappe-ui/src/resources/resources.js'
  )
  const { setConfig } = await import('frappe-ui')
  setConfig('resourceFetcher', async ({ url }) => {
    requests.push(url)
    if (url === 'crm.api.session.get_users') return [[user], [user]]
    if (url === 'crm.api.access.get_visibility') return { role, hidden }
    if (url === 'crm.api.views.get_views') return views()
    return null
  })
  // stubbed, not written: the session store only reads it
  vi.spyOn(document, 'cookie', 'get').mockReturnValue(
    `user_id=${encodeURIComponent(REP)}`,
  )
  setActivePinia(createPinia())
  const router = (await import('@/router')).default
  return { router, requests }
}

async function navigate(router, path) {
  try {
    await router.push(path)
    return router.currentRoute.value.name
  } catch (error) {
    return `failed: ${error?.message || error}`
  }
}

beforeEach(() => vi.spyOn(console, 'error').mockImplementation(() => {}))

describe('a failed get_views', () => {
  /* frappe-ui starts an `auto` resource with a bare `fetch()`, so the boot
     request's failure is an unhandled rejection whatever the app does with
     it -- set aside for these tests, and checked to be that and nothing
     else. */
  let vitestListeners, unhandled
  const recordUnhandled = (reason) => unhandled.push(String(reason?.message))
  beforeEach(() => {
    unhandled = []
    vitestListeners = process.listeners('unhandledRejection')
    process.removeAllListeners('unhandledRejection')
    process.on('unhandledRejection', recordUnhandled)
  })
  afterEach(async () => {
    await new Promise((r) => setTimeout(r, 0))
    process.off('unhandledRejection', recordUnhandled)
    for (const listener of vitestListeners) {
      process.on('unhandledRejection', listener)
    }
    expect(unhandled.every((m) => m === '504 Gateway Time-out')).toBe(true)
  })

  it('does not wedge the list routes for the life of the tab', async () => {
    // One transient failure: a 504 during a deploy, a timeout.
    let failuresLeft = 1
    const { router, requests } = await bootTab({
      views: () => {
        if (failuresLeft-- > 0) throw new Error('504 Gateway Time-out')
        return []
      },
    })

    // The lists still open, on their default view, while views are down...
    expect(await navigate(router, '/leads')).toBe('Leads')
    expect(router.currentRoute.value.params.viewType).toBe('list')

    // ...and the next navigation asks again rather than rethrowing the
    // rejection it kept from boot.
    expect(await navigate(router, '/deals')).toBe('Deals')
    expect(
      requests.filter((u) => u === 'crm.api.views.get_views'),
    ).toHaveLength(2)
  })

  it("does not wedge a manager's Home", async () => {
    const { router } = await bootTab({
      role: 'Sales Manager',
      views: () => {
        throw new Error('504 Gateway Time-out')
      },
    })
    expect(await navigate(router, '/')).toBe('Leads')
  })
})

describe("a rep's Home", () => {
  const noViews = () => []

  it('is the Planner', async () => {
    const { router } = await bootTab({ views: noViews })
    expect(await navigate(router, '/')).toBe('Planner')
  })

  it('is Leads when Access Control hid the Planner', async () => {
    const { router } = await bootTab({
      hidden: ['nav.planner'],
      views: noViews,
    })
    expect(await navigate(router, '/')).toBe('Leads')
  })

  it('is the first surface left visible when Leads is hidden as well', async () => {
    // Landing on a hidden surface puts the rep on a page with no nav entry to
    // get back to -- the reason the Planner check exists at all.
    const { router } = await bootTab({
      hidden: ['nav.planner', 'nav.leads'],
      views: noViews,
    })
    expect(await navigate(router, '/')).toBe('Deals')

    const second = await bootTab({
      hidden: ['nav.planner', 'nav.leads', 'nav.deals'],
      views: noViews,
    })
    expect(await navigate(second.router, '/')).toBe('Organizations')
  })
})
