import { beforeEach, describe, it, expect, vi } from 'vitest'
import { createApp, defineComponent, h } from 'vue'

/* Node's own `localStorage` global (undefined without --localstorage-file)
   shadows happy-dom's; give the bus a real one. */
const mem = new Map()
const storage = {
  getItem: (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => mem.set(k, String(v)),
  removeItem: (k) => mem.delete(k),
  clear: () => mem.clear(),
}
for (const target of new Set([globalThis, window])) {
  Object.defineProperty(target, 'localStorage', {
    configurable: true,
    value: storage,
  })
}

const { broadcastBus, useBroadcast } = await import(
  '@/composables/useBroadcast'
)

describe('broadcastBus', () => {
  it('delivers the event detail to the handler', () => {
    const handler = vi.fn()
    broadcastBus.on('ping', handler)
    window.dispatchEvent(new CustomEvent('ping', { detail: { a: 1 } }))
    expect(handler).toHaveBeenCalledWith({ a: 1 })
    broadcastBus.off('ping', handler)
  })

  it('off removes the listener registered by on', () => {
    const handler = vi.fn()
    broadcastBus.on('pong', handler)
    broadcastBus.off('pong', handler)
    window.dispatchEvent(new CustomEvent('pong', { detail: 1 }))
    expect(handler).not.toHaveBeenCalled()
  })

  it('off tolerates a handler that was never registered', () => {
    expect(() => broadcastBus.off('nope', () => {})).not.toThrow()
  })
})

describe('useBroadcast', () => {
  function mountListener(event, handler) {
    const Listener = defineComponent({
      setup() {
        useBroadcast().on(event, handler)
        return () => h('div')
      },
    })
    const app = createApp(Listener)
    app.mount(document.createElement('div'))
    return app
  }

  beforeEach(() => storage.clear())

  it('does not replay a broadcast a mounted listener already handled', () => {
    // "Create your first lead" clicked while the Leads page is on screen:
    // the modal opened, and must not open again on the next visit to Leads.
    const opened = []
    const first = mountListener('trigger_lead_create', (d) =>
      opened.push(['first visit', d]),
    )
    broadcastBus.send('trigger_lead_create', true)
    expect(opened).toEqual([['first visit', true]])

    first.unmount()
    mountListener('trigger_lead_create', (d) => opened.push(['next visit', d]))
    expect(opened).toEqual([['first visit', true]])
  })

  it('replays a broadcast nobody was listening for, once, on the next mount', () => {
    // sent before the page that listens for it has mounted
    broadcastBus.send('email_template_page', { page: 'new-template' })
    const received = []
    const app = mountListener('email_template_page', (d) => received.push(d))
    expect(received).toEqual([{ page: 'new-template' }])

    app.unmount()
    mountListener('email_template_page', (d) => received.push(d))
    expect(received).toHaveLength(1)
  })

  it('keeps one pending copy of an event, not a pile', () => {
    // three template saves while no selector was mounted: one reload, not three
    broadcastBus.send('refresh-email-templates')
    broadcastBus.send('refresh-email-templates')
    broadcastBus.send('refresh-email-templates')
    const reloads = vi.fn()
    mountListener('refresh-email-templates', reloads)
    expect(reloads).toHaveBeenCalledOnce()
  })

  it('stores again once the listener has unmounted', () => {
    const handler = vi.fn()
    mountListener('reload-deal-sections', handler).unmount()
    broadcastBus.send('reload-deal-sections')
    expect(handler).not.toHaveBeenCalled()
    mountListener('reload-deal-sections', handler)
    expect(handler).toHaveBeenCalledOnce()
  })
})
