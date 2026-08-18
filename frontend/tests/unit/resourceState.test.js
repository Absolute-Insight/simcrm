import { describe, it, expect } from 'vitest'
import { neverLoaded } from '../../src/utils/resourceState.js'

/**
 * The rule exists because a count that never loaded and a count of zero render
 * identically — a hidden badge — and on the suggestion inbox that is the
 * product telling a rep there is no work waiting when it never managed to ask.
 */
describe('neverLoaded', () => {
  it('is false before anything has happened', () => {
    expect(neverLoaded({ data: 0, fetched: false, error: null })).toBe(false)
  })

  it('is false while a first fetch is still in flight', () => {
    expect(
      neverLoaded({ data: 0, fetched: false, error: null, loading: true }),
    ).toBe(false)
  })

  it('is true when the first fetch failed', () => {
    expect(
      neverLoaded({ data: 0, fetched: false, error: new Error('500') }),
    ).toBe(true)
  })

  /* The distinction the whole function exists for: frappe-ui restores
     previousData on a failed reload, so there IS a real number to show, and
     covering it with "unavailable" would be its own small lie. */
  it('is false when a reload failed but a value had already loaded', () => {
    expect(
      neverLoaded({ data: 378, fetched: true, error: new Error('500') }),
    ).toBe(false)
  })

  it('is false once loaded successfully', () => {
    expect(neverLoaded({ data: 12, fetched: true, error: null })).toBe(false)
  })

  it('treats a genuine zero as loaded, not as missing', () => {
    expect(neverLoaded({ data: 0, fetched: true, error: null })).toBe(false)
  })

  it('does not throw on a resource that is not there yet', () => {
    expect(neverLoaded(undefined)).toBe(false)
    expect(neverLoaded(null)).toBe(false)
  })
})
