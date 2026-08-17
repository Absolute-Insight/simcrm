import { describe, it, expect, beforeEach, vi } from 'vitest'

/**
 * `isMobileView` was `computed(() => window.innerWidth < 768)` — a computed over
 * a source Vue cannot track. It evaluated once and cached that answer for the
 * life of the page, so every `v-if="isMobileView"` in the app was written as
 * though it were live and none of them were.
 *
 * The module wires its listener at import time, so each test installs its own
 * `matchMedia` stub and then imports a fresh copy via `resetModules`.
 */

/**
 * The module registers one query per breakpoint (mobile, and the dashboard's
 * wide-grid width), so the stub keys them by media string. A single shared
 * query object would pool every breakpoint's listeners together and make
 * "subscribes once" unmeasurable.
 */
function installMatchMedia({ matches, modern = true }) {
  const queries = new Map()
  const listenersFor = new Map()

  window.matchMedia = (media) => {
    if (!queries.has(media)) {
      const listeners = []
      listenersFor.set(media, listeners)
      queries.set(media, {
        matches,
        media,
        ...(modern
          ? { addEventListener: (_event, fn) => listeners.push(fn) }
          : { addListener: (fn) => listeners.push(fn) }),
        removeEventListener: () => {},
        removeListener: () => {},
      })
    }
    return queries.get(media)
  }

  return {
    // what the browser does when a breakpoint is crossed
    cross(nowMatches) {
      for (const [media, query] of queries) {
        query.matches = nowMatches
        listenersFor.get(media).forEach((fn) => fn({ matches: nowMatches }))
      }
    },
    // listeners on the mobile query specifically, not pooled across breakpoints
    listenerCount: () => (listenersFor.get('(max-width: 767px)') || []).length,
    queryCount: () => queries.size,
  }
}

async function freshModule() {
  vi.resetModules()
  return import('../../src/composables/settings.js')
}

describe('isMobileView', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('reports the breakpoint state it was loaded at', async () => {
    installMatchMedia({ matches: true })
    const { isMobileView } = await freshModule()
    expect(isMobileView.value).toBe(true)
  })

  it('reports desktop when the query does not match', async () => {
    installMatchMedia({ matches: false })
    const { isMobileView } = await freshModule()
    expect(isMobileView.value).toBe(false)
  })

  it('follows the breakpoint being crossed', async () => {
    // The whole point. Before this it stayed on whatever it read first.
    const media = installMatchMedia({ matches: false })
    const { isMobileView } = await freshModule()
    expect(isMobileView.value).toBe(false)

    media.cross(true)
    expect(isMobileView.value).toBe(true)

    media.cross(false)
    expect(isMobileView.value).toBe(false)
  })

  it('subscribes exactly once, not once per reader', async () => {
    const media = installMatchMedia({ matches: false })
    const { isMobileView } = await freshModule()
    // read it a few times the way several components would
    void isMobileView.value
    void isMobileView.value
    expect(media.listenerCount()).toBe(1)
  })

  it('registers one query per breakpoint, not one shared one', async () => {
    const media = installMatchMedia({ matches: false })
    const { isMobileView, isNarrowGrid } = await freshModule()
    void isMobileView.value
    void isNarrowGrid.value
    expect(media.queryCount()).toBe(2)
  })

  it('tracks the dashboard grid width separately from mobile', async () => {
    // 700px is the case the grid fix is about: past the mobile breakpoint, but
    // still too narrow for twenty columns to divide into readable ones.
    const media = installMatchMedia({ matches: false })
    const { isNarrowGrid } = await freshModule()
    expect(isNarrowGrid.value).toBe(false)
    media.cross(true)
    expect(isNarrowGrid.value).toBe(true)
  })

  it('falls back to addListener where addEventListener is absent', async () => {
    // Safari < 14 has only the legacy form — absent, not deprecated.
    const media = installMatchMedia({ matches: false, modern: false })
    const { isMobileView } = await freshModule()
    media.cross(true)
    expect(isMobileView.value).toBe(true)
  })

  it('still answers when matchMedia is missing entirely', async () => {
    // A missing browser API must not take the module — and so the whole app —
    // down at import time.
    delete window.matchMedia
    window.innerWidth = 375
    const { isMobileView } = await freshModule()
    expect(isMobileView.value).toBe(true)
  })

  it('uses the same breakpoint the CSS does', async () => {
    installMatchMedia({ matches: false })
    const { MOBILE_BREAKPOINT_PX } = await freshModule()
    expect(MOBILE_BREAKPOINT_PX).toBe(768)
  })
})
