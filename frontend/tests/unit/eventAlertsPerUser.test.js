import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp } from 'vue'

// An event reminder (subject, place, times) waits in localStorage until it is
// dismissed. It is one user's: kept under that user's key, and removed with
// the rest of the per-user offline state. Each "page load" below is a fresh
// module graph, as it is in the browser.

// Node's own localStorage global shadows happy-dom's and is not usable here.
const mem = new Map()
const storage = {
  getItem: (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => mem.set(k, String(v)),
  removeItem: (k) => mem.delete(k),
  clear: () => mem.clear(),
  key: (i) => [...mem.keys()][i] ?? null,
  get length() {
    return mem.size
  },
}
for (const target of [globalThis, window]) {
  Object.defineProperty(target, 'localStorage', {
    value: storage,
    configurable: true,
  })
}

vi.mock('idb-keyval', () => ({
  createStore: () => new Map(),
  get: async () => undefined,
  set: async () => {},
  del: async () => {},
  clear: async () => {},
  entries: async () => [],
}))
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: null }),
}))
vi.mock('@/composables/event', () => ({ useEvent: () => ({}) }))
vi.mock('@/data/userSettings', () => ({
  getUserSettings: () => Promise.resolve({}),
  useUserSettings: () => ({ save: () => Promise.resolve() }),
}))

const OWNER = 'crm-offline-cache-owner'
const reminder = (subject) => ({
  event_name: 'EV-0001',
  subject,
  ends_on: '2099-01-01 10:00:00',
})

/** A page load for `user`: the guard first, then the app's modules. */
async function load(user, { guard = true } = {}) {
  vi.resetModules()
  document.cookie = `user_id=${encodeURIComponent(user)}`
  const cache = await import('@/utils/offlineCache')
  if (guard) await cache.claimOfflineCache(user)
  const { useEventNotificationAlert } = await import('@/data/notifications')
  let alerts
  const app = createApp({
    setup() {
      alerts = useEventNotificationAlert()
      return () => null
    },
  })
  app.mount(document.createElement('div'))
  return {
    alerts,
    cache,
    subjects: () =>
      alerts.activeAlerts.value.map((alert) => alert.notification.subject),
    // useStorage writes on the next tick; a page that closes has flushed
    leave: async () => {
      await new Promise((resolve) => setTimeout(resolve))
      app.unmount()
    },
  }
}

beforeEach(() => mem.clear())

describe('event reminders on a shared browser', () => {
  it("does not show the next user the previous user's reminder", async () => {
    const a = await load('a@example.com')
    a.alerts.handleEventNotification(reminder("A's private client call"))
    expect(a.subjects()).toEqual(["A's private client call"])
    await a.leave() // closed without logging out: nothing cleared anything

    const b = await load('b@example.com')
    expect(b.subjects()).toEqual([])
    expect(JSON.stringify([...mem])).not.toContain('private client call')
  })

  it('keeps reminders apart even where the guard never ran', async () => {
    const a = await load('a@example.com', { guard: false })
    a.alerts.handleEventNotification(reminder("A's private client call"))
    await a.leave()

    const b = await load('b@example.com', { guard: false })
    expect(b.subjects()).toEqual([])
  })

  it('still shows a user their own reminder after a reload', async () => {
    const first = await load('a@example.com')
    first.alerts.handleEventNotification(reminder('Site visit'))
    await first.leave()

    const second = await load('a@example.com')
    expect(second.subjects()).toEqual(['Site visit'])
  })

  it('removes a reminder left under the old key, which had no user in it', async () => {
    localStorage.setItem(OWNER, 'a@example.com')
    localStorage.setItem(
      'eventNotificationAlerts',
      JSON.stringify([
        { id: 'EV-0001', completed: false, notification: reminder('Old') },
      ]),
    )
    // the same user as before, so the stores are not cleared
    const a = await load('a@example.com')
    expect(a.subjects()).toEqual([])
    expect(localStorage.getItem('eventNotificationAlerts')).toBe(null)
  })

  it('removes every reminder on logout and on a lost session', async () => {
    const a = await load('a@example.com')
    a.alerts.handleEventNotification(reminder("A's private client call"))
    await a.leave()
    localStorage.setItem('eventNotificationAlerts', '[{"id":"legacy"}]')
    localStorage.setItem('theme', 'dark') // not a user's data: kept

    await a.cache.clearOfflineCache() // session.logout, sessionExpiry
    expect([...mem.keys()]).toEqual(['theme'])
  })
})
