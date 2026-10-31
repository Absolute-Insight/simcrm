import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import EnrichFromWebsite from '@/components/EnrichFromWebsite.vue'

const { call, toast, socket, reload } = vi.hoisted(() => ({
  call: vi.fn(),
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
  socket: { on: vi.fn(), off: vi.fn() },
  reload: vi.fn(),
}))

vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  call,
  toast,
}))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $socket: socket }),
}))
vi.mock('@/stores/organizations', () => ({
  organizationsStore: () => ({ organizations: { reload } }),
}))

const props = {
  doctype: 'CRM Organization',
  docname: 'Acme',
  website: 'https://acme.example',
}

function button(w) {
  return w.el.querySelector('button')
}

// Lets the click handler's awaited call() settle, under fake timers too.
async function click(w) {
  button(w).click()
  for (let i = 0; i < 5; i++) await Promise.resolve()
  await w.nextTick()
}

function progress(status, extra = {}) {
  const handler = socket.on.mock.calls.at(-1)[1]
  handler({
    reference_doctype: props.doctype,
    reference_name: props.docname,
    status,
    ...extra,
  })
}

describe('EnrichFromWebsite', () => {
  beforeEach(() => vi.clearAllMocks())
  afterEach(() => vi.useRealTimers())

  it('spins while a queued run is in flight and stops on its terminal event', async () => {
    call.mockResolvedValue({ queued: true, timeout: 690 })
    const w = mount(EnrichFromWebsite, { props })

    await click(w)
    expect(button(w).disabled).toBe(true)

    progress('completed', { payload: { filled_fields: ['Industry'] } })
    await w.nextTick()
    expect(button(w).disabled).toBe(false)
    expect(toast.success).toHaveBeenCalledOnce()
    expect(w.emitted.done).toHaveLength(1)
  })

  it('does not wait for a run it was folded into', async () => {
    // A click while the record's run is already queued (the nightly sweep's,
    // say) enqueues nothing; that run reports to whoever queued it, so no
    // event for this click is ever coming.
    call.mockResolvedValue({ queued: false, already_running: true })
    const w = mount(EnrichFromWebsite, { props })

    await click(w)

    expect(button(w).disabled).toBe(false)
    expect(socket.off).toHaveBeenCalled()
    expect(toast.info).toHaveBeenCalledOnce()
    expect(toast.info.mock.calls[0][0]).toMatch(/already/i)
  })

  it('gives up waiting once the job itself would have been stopped', async () => {
    // A worker killed outright never publishes a terminal event.
    vi.useFakeTimers()
    call.mockResolvedValue({ queued: true, timeout: 690 })
    const w = mount(EnrichFromWebsite, { props })

    await click(w)
    expect(button(w).disabled).toBe(true)

    await vi.advanceTimersByTimeAsync(689 * 1000)
    expect(button(w).disabled).toBe(true)

    await vi.advanceTimersByTimeAsync(120 * 1000)
    expect(button(w).disabled).toBe(false)
    expect(socket.off).toHaveBeenCalled()
    expect(toast.warning).toHaveBeenCalledOnce()
  })

  it('does not give up on a run that already reported back', async () => {
    vi.useFakeTimers()
    call.mockResolvedValue({ queued: true, timeout: 10 })
    const w = mount(EnrichFromWebsite, { props })

    await click(w)
    progress('completed', { payload: {} })
    await vi.advanceTimersByTimeAsync(600 * 1000)

    expect(toast.warning).not.toHaveBeenCalled()
    expect(button(w).disabled).toBe(false)
  })
})
