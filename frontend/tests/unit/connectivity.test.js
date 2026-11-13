import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * The connectivity gate, against a fetch that is told what the network is
 * doing. Each test is a fresh page load: the module's state -- online or not,
 * shell or not -- is decided at import.
 */
vi.mock('@/utils/sessionExpiry', () => ({
  redirectIfSessionGone: vi.fn(() => true),
}))

const HANDSHAKE = '/api/method/crm.api.offline.handshake'
const ok = (message) => ({
  ok: true,
  status: 200,
  json: async () => ({ message }),
})

async function load({ shell = false, onLine = true, fetch } = {}) {
  vi.resetModules()
  if (shell) window.__crm_offline_shell = true
  else delete window.__crm_offline_shell
  delete window.csrf_token
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(onLine)
  vi.stubGlobal('fetch', fetch ?? vi.fn(async () => ok({ csrf_token: 'tok' })))
  const mod = await import('@/offline/connectivity')
  const { redirectIfSessionGone } = await import('@/utils/sessionExpiry')
  return { ...mod, redirectIfSessionGone }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  delete window.__crm_offline_shell
  delete window.csrf_token
})

describe('the connectivity gate', () => {
  it('lets a request straight through on a normal page', async () => {
    const { throughGate } = await load()
    window.csrf_token = 'rendered-by-frappe'
    const send = vi.fn(async () => 'answer')
    expect(await throughGate(send)).toBe('answer')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('marks the app offline when a request fails the way a dead line does', async () => {
    const { throughGate, connectivity } = await load()
    window.csrf_token = 'rendered-by-frappe'
    await expect(
      throughGate(async () => {
        throw new TypeError('Failed to fetch')
      }),
    ).rejects.toThrow('Failed to fetch')
    expect(connectivity.online).toBe(false)
  })

  it('leaves it online when the server answered with an error', async () => {
    const { throughGate, connectivity } = await load()
    window.csrf_token = 'rendered-by-frappe'
    const refusal = Object.assign(new Error('nope'), {
      status: 417,
      exc_type: 'ValidationError',
    })
    await expect(
      throughGate(async () => {
        throw refusal
      }),
    ).rejects.toBe(refusal)
    expect(connectivity.online).toBe(true)
  })

  it('offline, fails at once as offline without sending the request', async () => {
    const { throughGate, connectivity } = await load({ onLine: false })
    expect(connectivity.online).toBe(false)
    const send = vi.fn()
    await expect(throughGate(send)).rejects.toMatchObject({
      name: 'TypeError',
      code: 'ERR_NETWORK',
    })
    expect(send).not.toHaveBeenCalled()
    // the browser said there is no network: nothing was sent to find out
    expect(fetch).not.toHaveBeenCalled()
  })

  it('a shell start is offline until the handshake, which brings the token', async () => {
    const { throughGate, connectivity } = await load({ shell: true })
    expect(connectivity.online).toBe(false)
    const send = vi.fn(async () => 'answer')
    expect(await throughGate(send)).toBe('answer')
    expect(fetch).toHaveBeenCalledWith(
      HANDSHAKE,
      expect.objectContaining({ method: 'GET' }),
    )
    expect(window.csrf_token).toBe('tok')
    expect(connectivity.online).toBe(true)
  })

  it('never sends a POST from a shell that could not get a token', async () => {
    const { throughGate } = await load({
      shell: true,
      fetch: vi.fn(async () => ok({})),
    })
    const send = vi.fn()
    await expect(throughGate(send)).rejects.toMatchObject({
      code: 'ERR_NETWORK',
    })
    expect(send).not.toHaveBeenCalled()
  })

  it('does not replace the token of a page Frappe rendered', async () => {
    const { probe } = await load()
    window.csrf_token = 'rendered-by-frappe'
    await probe()
    expect(window.csrf_token).toBe('rendered-by-frappe')
  })
})

describe('the probe', () => {
  it('measures how far the device clock is from the server’s', async () => {
    vi.setSystemTime(new Date('2026-11-13T10:00:00Z'))
    const { probe, connectivity, serverNow } = await load({
      fetch: vi.fn(async () =>
        ok({
          csrf_token: 'tok',
          server_epoch: Date.parse('2026-11-13T10:05:00Z') / 1000,
        }),
      ),
    })
    expect(await probe()).toBe(true)
    expect(connectivity.skewMs).toBe(5 * 60 * 1000)
    expect(serverNow()).toBe(Date.parse('2026-11-13T10:05:00Z'))
  })

  it('shares one request between callers that ask together', async () => {
    const { probe } = await load()
    await Promise.all([probe(), probe(), probe()])
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('a refusal is the server answering: online, and off to log in', async () => {
    const { probe, connectivity, redirectIfSessionGone } = await load({
      shell: true,
      fetch: vi.fn(async () => ({ ok: false, status: 403 })),
    })
    expect(await probe()).toBe(false)
    expect(connectivity.online).toBe(true)
    expect(redirectIfSessionGone).toHaveBeenCalledWith({ status: 403 })
  })

  it('a failed probe stays offline and tries again later', async () => {
    let up = false
    const { probe, connectivity } = await load({
      fetch: vi.fn(async () => {
        if (!up) throw new TypeError('Failed to fetch')
        return ok({ csrf_token: 'tok' })
      }),
    })
    expect(await probe()).toBe(false)
    expect(connectivity.online).toBe(false)
    up = true
    await vi.advanceTimersByTimeAsync(5000)
    expect(connectivity.online).toBe(true)
  })

  it('tells whoever is listening when the server is back', async () => {
    let up = false
    const { probe, onOnline } = await load({
      fetch: vi.fn(async () => {
        if (!up) throw new TypeError('Failed to fetch')
        return ok({ csrf_token: 'tok' })
      }),
    })
    const heard = vi.fn()
    onOnline(heard)
    await probe()
    expect(heard).not.toHaveBeenCalled()
    up = true
    await probe()
    expect(heard).toHaveBeenCalledOnce()
  })

  it('a 5xx is not "online"', async () => {
    const { probe, connectivity } = await load({
      fetch: vi.fn(async () => ({ ok: false, status: 502 })),
    })
    expect(await probe()).toBe(false)
    expect(connectivity.online).toBe(false)
  })
})
