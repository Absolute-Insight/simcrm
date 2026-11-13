import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * The connectivity gate, against a fetch that is told what the network is
 * doing. Each test is a fresh page load: the module's state -- online or not,
 * shell or not -- is decided at import.
 */
vi.mock('@/utils/sessionExpiry', () => ({
  redirectIfSessionGone: vi.fn(() => true),
}))
vi.mock('@/utils/offlineCache', () => ({
  clearOfflineCache: vi.fn(async () => {}),
}))

const HANDSHAKE = '/api/method/crm.api.offline.handshake'
const refusal = () => ({
  ok: false,
  status: 403,
  json: async () => ({ exc_type: 'PermissionError', session_expired: 1 }),
})
const ok = (message) => ({
  ok: true,
  status: 200,
  json: async () => ({ message }),
})

const REP = 'rep@example.com'

async function load({ shell = false, onLine = true, fetch } = {}) {
  vi.resetModules()
  if (shell) {
    window.__crm_offline_shell = true
    window.__crm_offline_user = REP
  } else {
    delete window.__crm_offline_shell
    delete window.__crm_offline_user
  }
  delete window.csrf_token
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(onLine)
  vi.stubGlobal(
    'fetch',
    fetch ?? vi.fn(async () => ok({ csrf_token: 'tok', user: REP })),
  )
  const reload = vi.fn()
  vi.stubGlobal('location', { hostname: 'crm.test', reload })
  const mod = await import('@/offline/connectivity')
  const { redirectIfSessionGone } = await import('@/utils/sessionExpiry')
  const { clearOfflineCache } = await import('@/utils/offlineCache')
  return { ...mod, redirectIfSessionGone, clearOfflineCache, reload }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  delete window.__crm_offline_shell
  delete window.__crm_offline_user
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

  it('a request that died is a reason to ask, not proof: the probe decides', async () => {
    const { throughGate, connectivity } = await load()
    window.csrf_token = 'rendered-by-frappe'
    const dropped = () =>
      throughGate(async () => {
        throw new TypeError('Failed to fetch')
      })
    // a laptop waking from sleep: one fetch lost, the server is there
    await expect(dropped()).rejects.toThrow('Failed to fetch')
    await vi.advanceTimersByTimeAsync(0)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(connectivity.online).toBe(true)
  })

  it('goes offline when the probe that follows fails too', async () => {
    const { throughGate, connectivity } = await load({
      fetch: vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    })
    window.csrf_token = 'rendered-by-frappe'
    await expect(
      throughGate(async () => {
        throw new TypeError('Failed to fetch')
      }),
    ).rejects.toThrow('Failed to fetch')
    await vi.advanceTimersByTimeAsync(0)
    expect(connectivity.online).toBe(false)
  })

  it('after a failed probe, requests fail at once instead of each probing', async () => {
    const { throughGate, probe } = await load({
      fetch: vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    })
    await probe()
    expect(fetch).toHaveBeenCalledTimes(1)
    for (let i = 0; i < 5; i++) {
      await expect(throughGate(vi.fn())).rejects.toMatchObject({
        code: 'ERR_NETWORK',
      })
    }
    expect(fetch).toHaveBeenCalledTimes(1)
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
      fetch: vi.fn(async () => ok({ user: REP })),
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

  it('does replace it when asked to: the server said that token is no good', async () => {
    const { renewToken } = await load()
    window.csrf_token = 'the-old-sessions'
    expect(await renewToken()).toBe(true)
    expect(window.csrf_token).toBe('tok')
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('a renewal does not settle for a probe already on its way', async () => {
    const { probe, renewToken } = await load()
    window.csrf_token = 'the-old-sessions'
    const first = probe()
    const renewed = renewToken()
    expect(renewToken()).toBe(renewed)
    await first
    expect(await renewed).toBe(true)
    expect(window.csrf_token).toBe('tok')
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('a renewal that cannot reach the server says so and keeps what it had', async () => {
    const { renewToken, connectivity } = await load({
      fetch: vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    })
    window.csrf_token = 'the-old-sessions'
    expect(await renewToken()).toBe(false)
    expect(window.csrf_token).toBe('the-old-sessions')
    expect(connectivity.online).toBe(false)
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
      fetch: vi.fn(async () => refusal()),
    })
    expect(await probe()).toBe(false)
    expect(connectivity.online).toBe(true)
    expect(redirectIfSessionGone).toHaveBeenCalledWith(
      expect.objectContaining({ status: 403, session_expired: 1 }),
    )
  })

  it('a 403 that is not Frappe’s is an unreachable server, not a refusal', async () => {
    const { probe, connectivity, clearOfflineCache, reload } = await load({
      shell: true,
      // a proxy's block page: no JSON, nothing about the session
      fetch: vi.fn(async () => ({
        ok: false,
        status: 403,
        json: async () => {
          throw new SyntaxError('Unexpected token <')
        },
      })),
    })
    expect(await probe()).toBe(false)
    await vi.advanceTimersByTimeAsync(0)
    expect(connectivity.online).toBe(false)
    expect(clearOfflineCache).not.toHaveBeenCalled()
    expect(reload).not.toHaveBeenCalled()
  })

  it('a refused request reads as permission, not as offline', async () => {
    const { probe, throughGate } = await load({
      shell: true,
      fetch: vi.fn(async () => refusal()),
    })
    await probe()
    await expect(throughGate(vi.fn())).rejects.toMatchObject({
      status: 403,
      exc_type: 'PermissionError',
    })
    // and it does not ask again for every request that follows
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('a shell the server refuses gives up what it holds and reloads', async () => {
    const { probe, clearOfflineCache, reload } = await load({
      shell: true,
      fetch: vi.fn(async () => refusal()),
    })
    await probe()
    await vi.advanceTimersByTimeAsync(0)
    expect(clearOfflineCache).toHaveBeenCalledOnce()
    expect(reload).toHaveBeenCalledOnce()
  })

  it('a shell showing one rep while the session is another’s does the same', async () => {
    const { probe, clearOfflineCache, reload } = await load({
      shell: true,
      fetch: vi.fn(async () =>
        ok({ csrf_token: 'tok', user: 'someone.else@example.com' }),
      ),
    })
    expect(await probe()).toBe(false)
    await vi.advanceTimersByTimeAsync(0)
    expect(clearOfflineCache).toHaveBeenCalledOnce()
    expect(reload).toHaveBeenCalledOnce()
    // and it never took the other session's token
    expect(window.csrf_token).toBeUndefined()
  })

  it('a failed probe stays offline and tries again later', async () => {
    let up = false
    const { probe, connectivity } = await load({
      fetch: vi.fn(async () => {
        if (!up) throw new TypeError('Failed to fetch')
        return ok({ csrf_token: 'tok', user: REP })
      }),
    })
    expect(await probe()).toBe(false)
    expect(connectivity.online).toBe(false)
    up = true
    await vi.advanceTimersByTimeAsync(5000)
    expect(connectivity.online).toBe(true)
  })

  it('a navigation waits a moment for the answer, then settles for field mode', async () => {
    let answer
    const { reachableForNavigation } = await load({
      shell: true,
      fetch: vi.fn(() => new Promise((resolve) => (answer = resolve))),
    })
    // a slow line that does answer keeps the page that was asked for
    const quick = reachableForNavigation()
    await vi.advanceTimersByTimeAsync(1000)
    answer(ok({ csrf_token: 'tok', user: REP }))
    expect(await quick).toBe(true)
  })

  it('a navigation does not wait out a dead line', async () => {
    const { reachableForNavigation } = await load({
      shell: true,
      fetch: vi.fn(() => new Promise(() => {})),
    })
    const slow = reachableForNavigation()
    await vi.advanceTimersByTimeAsync(2500)
    expect(await slow).toBe(false)
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
