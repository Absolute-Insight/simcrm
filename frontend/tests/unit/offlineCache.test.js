import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest'

// frappe-ui keeps every `cache:` resource's last response in IndexedDB
// (idb-keyval) and replays it into the resource on the next page load, before
// the server answers. idb-keyval is replaced by a map that, like IndexedDB,
// outlives a page load; each "page load" below is a fresh module graph.
//
// Field mode keeps its pack in a second idb-keyval store (offline/db.js), so
// the mock tells the stores apart: a call that names a store goes to that
// store's own map, and the default store stays the one frappe-ui replays.
const { idb, packIdb } = vi.hoisted(() => ({
  idb: new Map(),
  packIdb: new Map(),
}))
vi.mock('idb-keyval', () => {
  const of = (store) => store ?? idb
  return {
    createStore: (database) =>
      database === 'vectora-field-pack' ? packIdb : new Map(),
    get: async (key, store) => of(store).get(key),
    set: async (key, value, store) => void of(store).set(key, value),
    del: async (key, store) => void of(store).delete(key),
    clear: async (store) => of(store).clear(),
    entries: async (store) => [...of(store).entries()],
  }
})
vi.mock('@/router', () => ({ default: { replace() {} } }))

const hadIndexedDB = 'indexedDB' in globalThis
globalThis.indexedDB ??= {} // frappe-ui only checks that it exists
afterAll(() => {
  if (!hadIndexedDB) delete globalThis.indexedDB
})

// Node's own localStorage global shadows happy-dom's and is not usable here;
// without one the owner is never remembered and every load clears (the safe
// side, but not what the same-user case is about).
const mem = new Map()
const storage = {
  getItem: (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => mem.set(k, String(v)),
  removeItem: (k) => mem.delete(k),
  clear: () => mem.clear(),
}
for (const target of [globalThis, window]) {
  Object.defineProperty(target, 'localStorage', {
    value: storage,
    configurable: true,
  })
}

const LEADS = ['CRM Lead', null, 'list']
const repAsLeads = {
  data: [{ name: 'CRM-LEAD-2026-00042', lead_name: 'Rep A private prospect' }],
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 5))

function setUserCookie(user) {
  document.cookie = `user_id=${encodeURIComponent(user)}; path=/`
}

// A page load of the SPA as `user`: main.js's first import claims the offline
// cache, then a list page creates its cached resource.
async function openLeads(user, answer) {
  vi.resetModules()
  setUserCookie(user)
  await import('@/offlineCacheGuard.js')
  const { createResource, setConfig } = await import('frappe-ui')
  setConfig('resourceFetcher', answer)
  const leads = createResource({
    url: 'crm.api.doc.get_data',
    cache: LEADS,
    auto: true,
  })
  await settle()
  return leads
}

const onTheWire = () => new Promise(() => {})

// Each "page load" re-imports frappe-ui. The first import transforms all of it,
// which takes seconds on a CI runner and must not count against a test's 5s
// limit.
beforeAll(() => import('frappe-ui'), 60_000)

beforeEach(() => {
  idb.clear()
  mem.clear()
})

describe('the offline cache belongs to one user', () => {
  // The longer timeout is for the file's first, cold import of frappe-ui, which
  // takes over 5s on a busy machine. Timing out leaves this test running into
  // the next one, which then fails too.
  it("never shows the next person to log in the previous rep's rows", async () => {
    await openLeads('rep.a@example.com', async () => repAsLeads)
    expect(idb.size).toBeGreaterThan(0) // what rep A left on disk

    // rep A logs out (in the desk, say); rep B logs in on the same browser
    const leads = await openLeads('rep.b@example.com', onTheWire)
    expect(leads.data).toBeNull()
    expect(idb.size).toBe(0)
  }, 30000)

  it('still replays it for the same rep coming back', async () => {
    await openLeads('rep.a@example.com', async () => repAsLeads)
    const leads = await openLeads('rep.a@example.com', onTheWire)
    expect(leads.data).toEqual(repAsLeads)
  })

  it('is cleared on logout, before the page leaves', async () => {
    await openLeads('rep.a@example.com', async () => repAsLeads)
    vi.resetModules()
    const { createPinia, setActivePinia } = await import('pinia')
    setActivePinia(createPinia())
    const { setConfig } = await import('frappe-ui')
    setConfig('resourceFetcher', async () => ({}))
    const { sessionStore } = await import('@/stores/session')

    let leftWithCache = null
    const location = window.location
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        set href(url) {
          leftWithCache = idb.size
        },
      },
    })
    try {
      sessionStore().logout.submit()
      await settle()
    } finally {
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: location,
      })
    }
    expect(leftWithCache).toBe(0)
  })

  it('a rep whose last session ended in a logout starts clean too', async () => {
    const { clearOfflineCache } = await import('@/utils/offlineCache')
    await openLeads('rep.a@example.com', async () => repAsLeads)
    await clearOfflineCache()
    // a response still in flight at logout lands after the clear
    idb.set(JSON.stringify(LEADS), JSON.stringify(repAsLeads))
    const leads = await openLeads('rep.a@example.com', onTheWire)
    expect(leads.data).toBeNull()
  })
})

describe('field mode shares the same owner', () => {
  beforeEach(() => {
    idb.clear()
    packIdb.clear()
    mem.clear()
    vi.resetModules()
  })

  it('drops the pack and the saved boot when another user takes the device', async () => {
    setUserCookie('rep.a@example.com')
    await import('@/offlineCacheGuard')
    await settle()
    packIdb.set('pack', { pack: { user: 'rep.a@example.com' } })
    storage.setItem('crm-offline-boot', '{"user":"rep.a@example.com"}')

    vi.resetModules()
    setUserCookie('rep.b@example.com')
    await import('@/offlineCacheGuard')
    await settle()

    expect(packIdb.size).toBe(0)
    expect(storage.getItem('crm-offline-boot')).toBeNull()
  })

  it('keeps both for the same rep coming back', async () => {
    setUserCookie('rep.a@example.com')
    await import('@/offlineCacheGuard')
    await settle()
    packIdb.set('pack', { pack: { user: 'rep.a@example.com' } })
    storage.setItem('crm-offline-boot', '{"user":"rep.a@example.com"}')

    vi.resetModules()
    await import('@/offlineCacheGuard')
    await settle()

    expect(packIdb.size).toBe(1)
    expect(storage.getItem('crm-offline-boot')).not.toBeNull()
  })

  it('a cached shell with no cookie keeps the stores of the user it booted as', async () => {
    setUserCookie('rep.a@example.com')
    await import('@/offlineCacheGuard')
    await settle()
    packIdb.set('pack', { pack: { user: 'rep.a@example.com' } })

    // the phone closed the app: the session cookie is gone, the shell's
    // loader matched the owner against the saved boot
    vi.resetModules()
    setUserCookie('')
    window.__crm_offline_shell = true
    window.__crm_offline_user = 'rep.a@example.com'
    try {
      await import('@/offlineCacheGuard')
      await settle()
      expect(packIdb.size).toBe(1)
      expect(storage.getItem('crm-offline-cache-owner')).toBe(
        'rep.a@example.com',
      )
    } finally {
      delete window.__crm_offline_shell
      delete window.__crm_offline_user
    }
  })

  it('a cached shell that says Guest is a logout, and clears', async () => {
    setUserCookie('rep.a@example.com')
    await import('@/offlineCacheGuard')
    await settle()
    packIdb.set('pack', { pack: { user: 'rep.a@example.com' } })

    vi.resetModules()
    setUserCookie('Guest')
    window.__crm_offline_shell = true
    try {
      await import('@/offlineCacheGuard')
      await settle()
      expect(packIdb.size).toBe(0)
    } finally {
      delete window.__crm_offline_shell
    }
  })
})
