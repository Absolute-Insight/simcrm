import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, ref } from 'vue'
import { LAZY_DELAY_MS, lazyComponent } from '@/utils/lazyComponent'

const Real = {
  props: ['value'],
  emits: ['change'],
  render() {
    return h(
      'p',
      { id: 'real', onClick: () => this.$emit('change', 'typed') },
      [this.value, this.$slots.default?.()],
    )
  },
}
const Loading = { render: () => h('p', { id: 'loading' }, 'loading') }
const Failed = {
  props: ['error'],
  emits: ['retry'],
  render() {
    return h(
      'button',
      { id: 'failed', onClick: () => this.$emit('retry') },
      this.error.message,
    )
  },
}

function mount(component, props = {}) {
  const el = document.createElement('div')
  const app = createApp({ render: () => h(component, props, () => ' slot') })
  el.errors = []
  app.config.errorHandler = (error) => el.errors.push(error.message)
  app.mount(el)
  el.unmount = () => app.unmount()
  return el
}
const settle = async () => {
  for (let i = 0; i < 5; i++) {
    await Promise.resolve()
    await nextTick()
  }
}
const gate = () => {
  const loads = []
  const loader = () =>
    new Promise((resolve, reject) => loads.push({ resolve, reject }))
  return { loads, loader }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.spyOn(console, 'error').mockImplementation(() => {})
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('lazyComponent', () => {
  it('draws nothing in its place for a load that is quick', async () => {
    const { loads, loader } = gate()
    const el = mount(lazyComponent(loader, { loading: Loading }))
    await vi.advanceTimersByTimeAsync(LAZY_DELAY_MS - 1)
    expect(el.querySelector('#loading')).toBeNull()
    loads[0].resolve({ default: Real })
    await settle()
    expect(el.querySelector('#real')).not.toBeNull()
    await vi.advanceTimersByTimeAsync(LAZY_DELAY_MS)
    expect(el.querySelector('#loading')).toBeNull()
  })

  it('shows the stand-in once a load has taken long enough to notice', async () => {
    const { loads, loader } = gate()
    const el = mount(lazyComponent(loader, { loading: Loading }))
    await vi.advanceTimersByTimeAsync(LAZY_DELAY_MS + 1)
    expect(el.querySelector('#loading')).not.toBeNull()
    loads[0].resolve({ default: Real })
    await settle()
    expect(el.querySelector('#loading')).toBeNull()
    expect(el.querySelector('#real')).not.toBeNull()
  })

  it('passes props, listeners and slots through to what it loaded', async () => {
    const changed = []
    const el = mount(
      lazyComponent(async () => ({ default: Real })),
      { value: 'hello', onChange: (v) => changed.push(v) },
    )
    await settle()
    expect(el.querySelector('#real').textContent).toBe('hello slot')
    el.querySelector('#real').click()
    expect(changed).toEqual(['typed'])
  })

  it('leaves a retry in its place when the load fails, and loads on the retry', async () => {
    const { loads, loader } = gate()
    const failures = []
    const el = mount(
      lazyComponent(loader, {
        failed: Failed,
        onFail: (error) => failures.push(error.message),
      }),
    )
    await settle()
    loads[0].reject(new Error('Failed to fetch dynamically imported module'))
    await settle()
    // not nothing: the field would have vanished from its form
    expect(el.querySelector('#failed').textContent).toBe(
      'Failed to fetch dynamically imported module',
    )
    expect(failures).toHaveLength(1)

    el.querySelector('#failed').click()
    await settle()
    expect(loads).toHaveLength(2)
    expect(el.querySelector('#failed')).toBeNull()
    loads[1].resolve({ default: Real })
    await settle()
    expect(el.querySelector('#real')).not.toBeNull()
    expect(el.errors).toEqual([])
  })

  it('never reloads the page, whatever the failure looks like', async () => {
    // A form is open around it. The router reloads once for a route whose
    // chunk a release removed; a component must not, or a dropped connection
    // costs the user what they typed.
    const assign = vi.fn()
    const reload = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign, reload })
    try {
      for (const message of [
        'Failed to fetch dynamically imported module',
        'Importing a module script failed',
        'Unable to preload CSS',
        'boom',
      ]) {
        const el = mount(
          lazyComponent(() => Promise.reject(new Error(message)), {
            failed: Failed,
          }),
        )
        await settle()
        expect(el.querySelector('#failed')).not.toBeNull()
      }
      expect(assign).not.toHaveBeenCalled()
      expect(reload).not.toHaveBeenCalled()
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('a failed load is tried again by the next instance to mount', async () => {
    const { loads, loader } = gate()
    const Lazy = lazyComponent(loader, { failed: Failed })
    const first = mount(Lazy)
    await settle()
    loads[0].reject(new Error('offline'))
    await settle()
    first.unmount()

    const second = mount(Lazy)
    await settle()
    expect(loads).toHaveLength(2)
    loads[1].resolve({ default: Real })
    await settle()
    expect(second.querySelector('#real')).not.toBeNull()
  })

  it('is there at once every time after the first', async () => {
    let fetched = 0
    const Lazy = lazyComponent(async () => {
      fetched++
      return { default: Real }
    })
    mount(Lazy)
    await settle()
    const el = mount(Lazy)
    expect(el.querySelector('#real')).not.toBeNull() // no tick in between
    expect(fetched).toBe(1)
  })

  it('does not write to an instance that left before its load came back', async () => {
    const { loads, loader } = gate()
    const show = ref(true)
    const Lazy = lazyComponent(loader, { failed: Failed })
    const el = document.createElement('div')
    const app = createApp({ render: () => (show.value ? h(Lazy) : null) })
    app.mount(el)
    show.value = false
    await settle()
    await settle()
    loads[0].reject(new Error('late'))
    await settle()
    expect(el.querySelector('#failed')).toBeNull()
  })
})
