import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

const backend = vi.hoisted(() => ({ running: false, calls: [] }))

vi.mock('frappe-ui', async (importOriginal) => {
  const { reactive } = await import('vue')
  return {
    ...(await importOriginal()),
    call: async (method) => {
      backend.calls.push(method)
      if (method.endsWith('.get_sync_status')) {
        return {
          last_synced_at: '2026-10-30 00:00:00',
          open_issues: 0,
          running: backend.running,
          last_sync_error: '',
          pending_retries: 0,
        }
      }
      if (method.endsWith('.get_open_sync_issues')) return []
      throw new Error(`unexpected call ${method}`)
    },
    toast: { success: () => {}, error: () => {}, info: () => {} },
    createDocumentResource: () =>
      reactive({
        doc: { enabled: 1, instance_url: 'https://erp.example.com' },
        get: { error: null },
        save: { loading: false, submit: async () => {} },
        reload: () => {},
      }),
  }
})
vi.mock('@/components/Controls/Link.vue', () => ({
  default: { render: () => null },
}))

const { default: AcumaticaSettings } = await import(
  '@/components/Settings/AcumaticaSettings.vue'
)

const statusReads = () =>
  backend.calls.filter((m) => m.endsWith('.get_sync_status')).length
const runBackfill = (el) =>
  [...el.querySelectorAll('button')].find(
    (b) => b.textContent.trim() === 'Run backfill',
  )

describe('AcumaticaSettings sync status', () => {
  beforeEach(() => {
    backend.calls.length = 0
    vi.useFakeTimers()
  })
  afterEach(() => vi.useRealTimers())

  it('follows a sync that was already running when the pane opened', async () => {
    // The nightly sweep, a webhook or another admin started it: polling used to
    // begin only from this tab's own Run backfill, so "running" and a disabled
    // button stayed on screen until a reload.
    backend.running = true
    const w = mount(AcumaticaSettings)
    await vi.advanceTimersByTimeAsync(0)
    expect(w.el.textContent).toContain('running')
    expect(runBackfill(w.el).disabled).toBe(true)

    backend.running = false
    await vi.advanceTimersByTimeAsync(5000)

    expect(w.el.textContent).toContain('idle')
    expect(runBackfill(w.el).disabled).toBe(false)
    // and it stops asking once the sync is over
    const reads = statusReads()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(statusReads()).toBe(reads)
  })

  it('does not poll an idle sync, nor keep polling after it is closed', async () => {
    backend.running = false
    const idle = mount(AcumaticaSettings)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(statusReads()).toBe(1)
    idle.unmount()

    backend.running = true
    const w = mount(AcumaticaSettings)
    await vi.advanceTimersByTimeAsync(0)
    w.unmount()
    const reads = statusReads()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(statusReads()).toBe(reads)
  })
})
