import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import { LAZY_DELAY_MS, lazyComponent } from '@/utils/lazyComponent'

const reloads = vi.hoisted(() => [])
vi.mock('@/utils/staleChunk', () => ({
  reloadOnceForStaleChunk: (error) => {
    const stale = /dynamically imported module/.test(error.message)
    if (stale) reloads.push(error.message)
    return stale
  },
}))

const Real = { render: () => h('p', { id: 'real' }, 'the dialog') }
const Loading = { render: () => h('p', { id: 'loading' }, 'loading') }

function mount(component) {
  const el = document.createElement('div')
  const app = createApp({ render: () => h(component) })
  app.config.warnHandler = () => {}
  // what Vue reports when a load fails for good
  el.errors = []
  app.config.errorHandler = (error) => el.errors.push(error.message)
  app.mount(el)
  return el
}
const settle = async () => {
  for (let i = 0; i < 5; i++) {
    await Promise.resolve()
    await nextTick()
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  reloads.length = 0
})
afterEach(() => vi.useRealTimers())

describe('lazyComponent', () => {
  it('draws nothing in its place for a load that is quick', async () => {
    let arrive
    const el = mount(
      lazyComponent(() => new Promise((r) => (arrive = r)), Loading),
    )
    await vi.advanceTimersByTimeAsync(LAZY_DELAY_MS - 1)
    expect(el.querySelector('#loading')).toBeNull()
    arrive(Real)
    await settle()
    expect(el.querySelector('#real')).not.toBeNull()
    await vi.advanceTimersByTimeAsync(LAZY_DELAY_MS)
    expect(el.querySelector('#loading')).toBeNull()
  })

  it('shows the stand-in once a load has taken long enough to notice', async () => {
    let arrive
    const el = mount(
      lazyComponent(() => new Promise((r) => (arrive = r)), Loading),
    )
    await vi.advanceTimersByTimeAsync(LAZY_DELAY_MS + 1)
    expect(el.querySelector('#loading')).not.toBeNull()
    arrive(Real)
    await settle()
    expect(el.querySelector('#loading')).toBeNull()
    expect(el.querySelector('#real')).not.toBeNull()
  })

  it('reloads once for a chunk a release removed', async () => {
    mount(
      lazyComponent(() =>
        Promise.reject(
          new Error('Failed to fetch dynamically imported module'),
        ),
      ),
    )
    await settle()
    expect(reloads).toHaveLength(1)
  })

  it('gives up on any other failure rather than reloading', async () => {
    const el = mount(lazyComponent(() => Promise.reject(new Error('boom'))))
    await settle()
    expect(reloads).toHaveLength(0)
    expect(el.errors).toEqual(['boom'])
    expect(el.querySelector('#real')).toBeNull()
  })
})
