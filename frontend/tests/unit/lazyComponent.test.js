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
  props: ['error', 'retrying'],
  emits: ['retry'],
  render() {
    return h(
      'button',
      {
        id: 'failed',
        'data-retrying': String(this.retrying),
        onClick: () => this.$emit('retry'),
      },
      this.error.message,
    )
  },
}

function mount(component, props = {}) {
  const el = document.createElement('div')
  const app = createApp({ render: () => h(component, props, () => ' slot') })
  app.config.globalProperties.__ = globalThis.__
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
    // the button stays while the retry runs, and says it is running
    expect(el.querySelector('#failed').dataset.retrying).toBe('true')
    loads[1].resolve({ default: Real })
    await settle()
    expect(el.querySelector('#failed')).toBeNull()
    expect(el.querySelector('#real')).not.toBeNull()
    expect(el.errors).toEqual([])
  })

  it('a retry that fails again leaves the retry there, no longer running', async () => {
    const { loads, loader } = gate()
    const el = mount(lazyComponent(loader, { failed: Failed }))
    await settle()
    loads[0].reject(new Error('first'))
    await settle()
    el.querySelector('#failed').click()
    await settle()
    loads[1].reject(new Error('second'))
    await settle()
    expect(el.querySelector('#failed').textContent).toBe('second')
    expect(el.querySelector('#failed').dataset.retrying).toBe('false')
  })

  it('moves focus into what loaded when the retry was started from the keyboard', async () => {
    const { loads, loader } = gate()
    const Field = { render: () => h('div', [h('input', { id: 'field' })]) }
    const el = mount(lazyComponent(loader, { failed: Failed }))
    document.body.appendChild(el) // focus needs a document
    try {
      await settle()
      loads[0].reject(new Error('offline'))
      await settle()
      const retry = el.querySelector('#failed')
      retry.focus()
      retry.click()
      await settle()
      expect(document.activeElement).toBe(retry) // not dropped to <body>
      loads[1].resolve({ default: Field })
      await settle()
      expect(document.activeElement).toBe(el.querySelector('#field'))
    } finally {
      el.remove()
    }
  })

  it('focuses the root of what loaded when nothing inside takes focus', async () => {
    const { loads, loader } = gate()
    const el = mount(lazyComponent(loader, { failed: Failed }))
    document.body.appendChild(el)
    try {
      await settle()
      loads[0].reject(new Error('offline'))
      await settle()
      el.querySelector('#failed').focus()
      el.querySelector('#failed').click()
      await settle()
      loads[1].resolve({ default: Real })
      await settle()
      expect(document.activeElement).toBe(el.querySelector('#real'))
    } finally {
      el.remove()
    }
  })

  it('leaves focus alone when it was somewhere else', async () => {
    const { loads, loader } = gate()
    const el = mount(lazyComponent(loader, { failed: Failed }))
    const elsewhere = document.createElement('input')
    document.body.append(el, elsewhere)
    try {
      await settle()
      loads[0].reject(new Error('offline'))
      await settle()
      el.querySelector('#failed').click()
      elsewhere.focus() // the user moved on while it loaded
      await settle()
      loads[1].resolve({ default: Real })
      await settle()
      expect(document.activeElement).toBe(elsewhere)
    } finally {
      el.remove()
      elsewhere.remove()
    }
  })

  it('shows a plain failure of its own when the caller named none', async () => {
    const el = mount(lazyComponent(() => Promise.reject(new Error('offline'))))
    await settle()
    const alert = el.querySelector('[role="alert"]')
    expect(alert.textContent).toContain('Could not load this part of the page')
    expect(
      [...alert.querySelectorAll('button')].some((b) =>
        b.textContent.includes('Try again'),
      ),
    ).toBe(true)
  })

  it('draws nothing for a caller that takes the failure on itself', async () => {
    const failures = []
    const el = mount(
      lazyComponent(() => Promise.reject(new Error('offline')), {
        onFail: (error) => failures.push(error.message),
      }),
    )
    await settle()
    expect(failures).toEqual(['offline'])
    expect(el.querySelector('[role="alert"]')).toBeNull()
  })

  it.each([
    ['undefined', undefined],
    ['a module with no default', { default: undefined }],
    ['null', null],
  ])('treats a loader that resolves %s as a failed load', async (_, value) => {
    const el = mount(lazyComponent(async () => value, { failed: Failed }))
    await settle()
    expect(el.querySelector('#failed').textContent).toBe(
      'The lazy component loaded as nothing',
    )
  })

  it('hands a template ref through to what the loaded component exposes', async () => {
    const { loads, loader } = gate()
    const Exposing = {
      setup(_, { expose }) {
        const count = ref(0)
        expose({ count, bump: () => ++count.value })
        return () => h('p', { id: 'exposing' }, count.value)
      },
    }
    const Lazy = lazyComponent(loader)
    const handle = ref(null)
    const el = document.createElement('div')
    createApp({ render: () => h(Lazy, { ref: handle }) }).mount(el)
    await settle()
    // not loaded yet: nothing behind the ref, and no throw for asking
    expect(handle.value.bump).toBeUndefined()
    expect('bump' in handle.value).toBe(false)
    loads[0].resolve({ default: Exposing })
    await settle()
    expect('bump' in handle.value).toBe(true)
    expect(handle.value.bump()).toBe(1)
    await settle()
    expect(el.querySelector('#exposing').textContent).toBe('1')
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
