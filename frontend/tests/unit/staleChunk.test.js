import { describe, expect, it, vi } from 'vitest'
import {
  isStaleChunkError,
  reloadOnceForStaleChunk,
  RELOAD_MARK,
} from '@/utils/staleChunk'

function memoryStorage(initial = {}) {
  const data = { ...initial }
  return {
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => {
      data[k] = v
    },
  }
}

describe('isStaleChunkError', () => {
  it("recognises the browsers' dynamic import failures", () => {
    expect(
      isStaleChunkError(
        new TypeError(
          'Failed to fetch dynamically imported module: /assets/x.js',
        ),
      ),
    ).toBe(true)
    expect(
      isStaleChunkError(new TypeError('Importing a module script failed.')),
    ).toBe(true)
    expect(
      isStaleChunkError({
        message: 'error loading dynamically imported module',
      }),
    ).toBe(true)
    expect(
      isStaleChunkError(new Error('Unable to preload CSS for /assets/x.css')),
    ).toBe(true)
  })
  it('leaves other errors alone', () => {
    expect(
      isStaleChunkError(new Error('Cannot read properties of undefined')),
    ).toBe(false)
    expect(isStaleChunkError(null)).toBe(false)
  })
})

describe('reloadOnceForStaleChunk', () => {
  const err = new TypeError('Failed to fetch dynamically imported module')

  it('reloads to the target the first time', () => {
    const reload = vi.fn()
    const storage = memoryStorage()
    expect(
      reloadOnceForStaleChunk(err, '/crm/deals', {
        storage,
        now: 1000,
        reload,
      }),
    ).toBe(true)
    expect(reload).toHaveBeenCalledWith('/crm/deals')
    expect(storage.getItem(RELOAD_MARK)).toBe('1000')
  })

  it('does not loop on a build that is broken for real', () => {
    const reload = vi.fn()
    const storage = memoryStorage({ [RELOAD_MARK]: '1000' })
    expect(
      reloadOnceForStaleChunk(err, '/crm/deals', {
        storage,
        now: 5000,
        reload,
      }),
    ).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })

  it('reloads again once the cooldown has passed', () => {
    const reload = vi.fn()
    const storage = memoryStorage({ [RELOAD_MARK]: '1000' })
    expect(
      reloadOnceForStaleChunk(err, '/crm/deals', {
        storage,
        now: 100_000,
        reload,
      }),
    ).toBe(true)
  })

  it('ignores unrelated errors', () => {
    const reload = vi.fn()
    expect(
      reloadOnceForStaleChunk(new Error('nope'), '/x', {
        storage: memoryStorage(),
        now: 1,
        reload,
      }),
    ).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })
})
