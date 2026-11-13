import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Syncing the pack, against a device (a map standing in for IndexedDB) and a
 * server that is told what to answer. Each test is a fresh page load.
 */
const { disk, server } = vi.hoisted(() => ({
  disk: new Map(),
  server: { answer: null, calls: [] },
}))
vi.mock('idb-keyval', () => ({
  createStore: (database) => database,
  get: async (key) => disk.get(key),
  set: async (key, value) => void disk.set(key, value),
  del: async (key) => void disk.delete(key),
  clear: async () => disk.clear(),
  entries: async () => [...disk.entries()],
}))
vi.mock('frappe-ui', () => ({
  call: async (method, args) => {
    server.calls.push({ method, ...args })
    return server.answer(args)
  },
}))
vi.mock('@/composables/settings', () => ({ isMobileView: { value: true } }))
vi.mock('@/utils/offlineCache', () => ({ offlineOwner: () => REP }))
vi.mock('@/utils/session', () => ({ getSessionUser: () => REP }))
vi.mock('@/offline/sheets', () => ({
  dropUnlistedSheets: async () => {},
  forgetSavedSheets: vi.fn(),
}))

globalThis.indexedDB ??= {}

const REP = 'rep@example.com'

const envelope = (sections) => ({
  user: REP,
  hash: Object.values(sections).join('+'),
  sections,
  generated_at: '2026-11-13 09:00:00',
  today: '2026-11-13',
  max_age_days: 14,
})

const full = () => ({
  ...envelope({ organizations: 'o1', notes: 'n1' }),
  unchanged: false,
  kept: [],
  organizations: [{ name: 'Impala' }],
  notes: [{ name: 'first' }],
})

async function load() {
  vi.resetModules()
  const { connectivity } = await import('@/offline/connectivity')
  connectivity.online = true
  return import('@/offline/pack')
}

beforeEach(() => {
  disk.clear()
  server.calls = []
  server.answer = async () => full()
})

describe('syncing the pack', () => {
  it('says which lists it already holds, and keeps the ones the server leaves out', async () => {
    const { syncPack, fieldPack } = await load()
    expect(await syncPack()).toBe(true)
    expect(server.calls[0].known_sections).toBeUndefined()

    // a note was written: the notes changed and the customers did not
    server.answer = async () => ({
      ...envelope({ organizations: 'o1', notes: 'n2' }),
      unchanged: false,
      kept: ['organizations'],
      notes: [{ name: 'second' }, { name: 'first' }],
    })
    expect(await syncPack()).toBe(true)
    expect(server.calls[1]).toMatchObject({
      known_hash: 'o1+n1',
      known_sections: { organizations: 'o1', notes: 'n1' },
    })
    expect(fieldPack.value.organizations).toEqual([{ name: 'Impala' }])
    expect(fieldPack.value.notes).toHaveLength(2)
    expect(fieldPack.value).toMatchObject({
      hash: 'o1+n2',
      sections: { organizations: 'o1', notes: 'n2' },
    })
    expect(fieldPack.value).not.toHaveProperty('kept')
    // and what is on the device is the whole pack, not the part that came
    expect(disk.get('pack').pack.organizations).toEqual([{ name: 'Impala' }])
  })

  it('asks for all of it when a list left out is not one it holds', async () => {
    const { syncPack, fieldPack } = await load()
    await syncPack()
    server.answer = async (args) =>
      args.known_sections
        ? {
            ...envelope({ organizations: 'o2', notes: 'n1' }),
            unchanged: false,
            // not what this device said it holds
            kept: ['organizations'],
            notes: [{ name: 'first' }],
          }
        : {
            ...full(),
            ...envelope({ organizations: 'o2', notes: 'n1' }),
            organizations: [{ name: 'Sibanye' }],
          }
    expect(await syncPack()).toBe(true)
    expect(server.calls).toHaveLength(3)
    expect(server.calls[2].known_sections).toBeUndefined()
    expect(server.calls[2].known_hash).toBeUndefined()
    expect(fieldPack.value.organizations).toEqual([{ name: 'Sibanye' }])
  })

  it('an unchanged pack is kept as it is, with the new day', async () => {
    const { syncPack, fieldPack } = await load()
    await syncPack()
    server.answer = async () => ({
      ...envelope({ organizations: 'o1', notes: 'n1' }),
      today: '2026-11-14',
      unchanged: true,
    })
    expect(await syncPack()).toBe(true)
    expect(fieldPack.value.organizations).toEqual([{ name: 'Impala' }])
    expect(fieldPack.value.today).toBe('2026-11-14')
  })
})
