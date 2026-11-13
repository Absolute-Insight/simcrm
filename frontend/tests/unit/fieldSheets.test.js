import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * Sheets kept on the device, against a map standing in for IndexedDB and a
 * fetch that is told what the server serves.
 */
const { disk } = vi.hoisted(() => ({ disk: new Map() }))
vi.mock('idb-keyval', () => ({
  createStore: (database) => database,
  get: async (key) => disk.get(key),
  set: async (key, value) => void disk.set(key, value),
  del: async (key) => void disk.delete(key),
  clear: async () => disk.clear(),
  entries: async () => [...disk.entries()],
}))
globalThis.indexedDB ??= {}

const png = (bytes = 2048) => ({
  ok: true,
  headers: { get: () => 'image/png' },
  blob: async () => ({ size: bytes, type: 'image/png' }),
})
const sheet = (overrides = {}) => ({
  name: 'flanges',
  title: 'Flange table',
  modified: '2026-11-01 10:00:00',
  pages: [
    {
      page: 1,
      image: '/private/files/flanges-p1.png',
      width: 800,
      height: 1100,
    },
    {
      page: 2,
      image: '/private/files/flanges-p2.png',
      width: 800,
      height: 1100,
    },
  ],
  ...overrides,
})

async function load(fetchImpl = vi.fn(async () => png())) {
  vi.resetModules()
  vi.stubGlobal('fetch', fetchImpl)
  return import('@/offline/sheets')
}

beforeEach(() => disk.clear())

describe('keeping a sheet', () => {
  it('stores every page and remembers what it holds', async () => {
    const { keepSheet, savedSheets, savedPages } = await load()
    await keepSheet(sheet())
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(fetch).toHaveBeenCalledWith(
      '/private/files/flanges-p1.png',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
    expect(savedSheets.byName.flanges).toEqual({
      modified: '2026-11-01 10:00:00',
      pages: 2,
      bytes: 4096,
    })
    expect((await savedPages('flanges')).map((p) => p.page)).toEqual([1, 2])
  })

  it('is still held after the app is closed and opened', async () => {
    await (await load()).keepSheet(sheet())
    const { loadSavedSheets, savedSheets } = await load()
    await loadSavedSheets()
    expect(Object.keys(savedSheets.byName)).toEqual(['flanges'])
  })

  it('keeps nothing when a page cannot be fetched', async () => {
    let n = 0
    const { keepSheet, savedSheets, savedPages } = await load(
      vi.fn(async () =>
        ++n === 2 ? { ok: false, headers: { get: () => '' } } : png(),
      ),
    )
    await expect(keepSheet(sheet())).rejects.toThrow(/could not be downloaded/)
    expect(savedSheets.byName).toEqual({})
    expect(await savedPages('flanges')).toBeNull()
    expect(savedSheets.saving).toBeNull()
  })

  it('refuses what is not an image: a login page served with a 200', async () => {
    const { keepSheet } = await load(
      vi.fn(async () => ({
        ok: true,
        headers: { get: () => 'text/html' },
        blob: async () => ({ size: 10 }),
      })),
    )
    await expect(keepSheet(sheet())).rejects.toThrow(/could not be downloaded/)
  })

  it('fetches only the site’s own file URLs, whatever the pack says', async () => {
    const { keepSheet } = await load()
    for (const image of [
      'https://elsewhere.example/p1.png',
      '//elsewhere.example/p1.png',
      '/api/method/frappe.client.get_list?doctype=User',
      '/files/../private/backups/site.sql',
      '/files/..',
      '/files/%2e%2e',
      '/private/files/..%2f..%2fapi%2fmethod%2fx',
      '/private/files/a%5cb.png',
      '/private/files/%zz.png',
      '',
    ]) {
      await expect(
        keepSheet(sheet({ pages: [{ page: 1, image }] })),
      ).rejects.toThrow()
    }
    expect(fetch).not.toHaveBeenCalled()
  })

  it('accepts the names the server actually stores', async () => {
    const { isSheetFileUrl } = await load()
    expect(isSheetFileUrl('/private/files/flanges-p1.png')).toBe(true)
    expect(isSheetFileUrl('/files/Valve%20chart%202.png')).toBe(true)
    expect(
      isSheetFileUrl('/private/files/qa-offline-flanges-p1a3f2c.png'),
    ).toBe(true)
  })

  it('a download that stalls is given up, and the tab is usable again', async () => {
    const { keepSheet, savedSheets } = await load(
      vi.fn(async (_url, { signal }) => {
        expect(signal).toBeDefined()
        throw new DOMException('timed out', 'TimeoutError')
      }),
    )
    await expect(keepSheet(sheet())).rejects.toThrow(/could not be downloaded/)
    expect(savedSheets.saving).toBeNull()
    expect(savedSheets.byName).toEqual({})
  })

  it('refuses a page too large to keep', async () => {
    const { keepSheet } = await load(vi.fn(async () => png(9 * 1024 * 1024)))
    await expect(keepSheet(sheet())).rejects.toThrow(/too large/)
  })

  it('a sheet the server no longer lists is dropped from the device', async () => {
    const { keepSheet, dropUnlistedSheets, savedSheets } = await load()
    await keepSheet(sheet())
    await keepSheet(sheet({ name: 'withdrawn' }))
    await dropUnlistedSheets(['flanges'])
    expect(Object.keys(savedSheets.byName)).toEqual(['flanges'])
    expect(disk.has('sheet:withdrawn')).toBe(false)
    expect(disk.has('sheet:flanges')).toBe(true)
  })

  it('can be removed', async () => {
    const { keepSheet, dropSheet, savedSheets, savedPages } = await load()
    await keepSheet(sheet())
    await dropSheet('flanges')
    expect(savedSheets.byName).toEqual({})
    expect(await savedPages('flanges')).toBeNull()
    expect(disk.has('sheet:flanges')).toBe(false)
  })
})
