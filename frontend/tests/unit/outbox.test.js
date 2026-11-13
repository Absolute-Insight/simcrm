import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * The outbox against a device (a map standing in for IndexedDB) and a server
 * that is told what to answer. Each test is a fresh page load.
 */
const { disk, server } = vi.hoisted(() => ({
  disk: new Map(),
  server: {
    replay: null,
    calls: [],
    syncs: 0,
    syncOk: true,
    user: 'rep@example.com',
  },
}))
vi.mock('idb-keyval', () => ({
  createStore: (database) => database,
  get: async (key) => disk.get(key),
  set: async (key, value) => void disk.set(key, value),
  del: async (key) => void disk.delete(key),
  clear: async () => disk.clear(),
  entries: async () => [...disk.entries()],
}))
vi.mock('frappe-ui', () => ({
  call: async (method, args) => {
    server.calls.push({ method, ...args })
    return server.replay(args)
  },
}))
vi.mock('@/offline/pack', () => {
  const listeners = new Set()
  return {
    packState: { refused: false },
    onPackSynced: (fn) => listeners.add(fn),
    // a sync that starts now and, when it works, stores a pack
    syncPackFresh: async () => {
      server.syncs += 1
      const startedAt = Date.now()
      await new Promise((resolve) => setTimeout(resolve, 1))
      if (server.syncOk) for (const fn of listeners) fn(startedAt)
      return server.syncOk
    },
    // a background sync somebody else started, at a time of the test's choosing
    backgroundSync: (startedAt) => {
      for (const fn of listeners) fn(startedAt)
    },
  }
})
vi.mock('@/utils/session', () => ({ getSessionUser: () => server.user }))

globalThis.indexedDB ??= {}

const refusal = (message) =>
  Object.assign(new Error(message), {
    status: 417,
    exc_type: 'ValidationError',
    messages: [message],
  })

async function load({ online = true } = {}) {
  vi.resetModules()
  const { connectivity } = await import('@/offline/connectivity')
  connectivity.online = online
  const mod = await import('@/offline/outbox')
  return { ...mod, connectivity }
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

beforeEach(() => {
  disk.clear()
  server.calls = []
  server.syncs = 0
  server.syncOk = true
  server.user = 'rep@example.com'
  server.replay = async () => ({ status: 'applied' })
  vi.spyOn(document, 'cookie', 'get').mockReturnValue(
    'user_id=rep%40example.com',
  )
  // the server is there and the session is the rep's, unless a test says not
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        message: { user: 'rep@example.com', csrf_token: 'tok' },
      }),
    })),
  )
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  delete window.csrf_token
})

describe('capturing', () => {
  it('offline, the entry is on the device and nothing is sent', async () => {
    const { enqueue, outbox } = await load({ online: false })
    const entry = await enqueue('create_task', { title: 'Order gaskets' })
    await settle()
    expect(disk.get(entry.id)).toMatchObject({
      action: 'create_task',
      status: 'pending',
      user: 'rep@example.com',
    })
    expect(outbox.entries).toHaveLength(1)
    expect(server.calls).toEqual([])
  })

  it('online, it is stored, sent with its id and time, then gone after a sync', async () => {
    const { enqueue, outbox, flushOutbox } = await load()
    const entry = await enqueue('create_task', { title: 'Order gaskets' })
    await flushOutbox()
    expect(server.calls).toEqual([
      {
        method: 'crm.api.offline.replay',
        request_id: entry.id,
        action: 'create_task',
        payload: { title: 'Order gaskets' },
        captured_at: entry.captured_at,
      },
    ])
    expect(server.syncs).toBe(1)
    expect(outbox.entries).toEqual([])
    expect(disk.size).toBe(0)
  })

  it('with nowhere to store it but a network, "saved" means the server has it', async () => {
    const { enqueue, outbox } = await load()
    disk.set = () => {
      throw new Error('QuotaExceeded')
    }
    try {
      await enqueue('create_task', { title: 'x' })
      expect(server.calls).toHaveLength(1)
      // and when the server refuses it, the rep is told why, not "saved"
      server.replay = async () => {
        throw refusal('Give the task a title.')
      }
      await expect(enqueue('create_task', { title: 'y' })).rejects.toThrow(
        'Give the task a title.',
      )
      expect(outbox.entries.some((e) => e.payload.title === 'y')).toBe(false)
    } finally {
      delete disk.set
    }
  })

  it('with nowhere to store it and no network, says so instead of "saved"', async () => {
    const { enqueue } = await load({ online: false })
    disk.set = () => {
      throw new Error('QuotaExceeded')
    }
    try {
      await expect(enqueue('create_task', { title: 'x' })).rejects.toThrow(
        /cannot save work offline/,
      )
    } finally {
      delete disk.set
    }
  })
})

describe('sending', () => {
  it('sends what waited, oldest first, when the server is back', async () => {
    const offline = await load({ online: false })
    const first = await offline.enqueue('create_task', { title: 'first' })
    const second = await offline.enqueue('create_task', { title: 'second' })
    // the phone was closed and opened again, with signal
    const { flushOutbox, outbox } = await load()
    await flushOutbox()
    expect(server.calls.map((c) => c.request_id)).toEqual([first.id, second.id])
    expect(outbox.entries).toEqual([])
  })

  it('sends the same id again after a lost answer', async () => {
    let attempts = 0
    server.replay = async () => {
      attempts += 1
      if (attempts === 1) throw new TypeError('Failed to fetch')
      return { status: 'duplicate' }
    }
    const { enqueue, flushOutbox, outbox } = await load()
    const entry = await enqueue('create_task', { title: 'x' })
    await flushOutbox()
    expect(outbox.entries[0].status).toBe('pending')
    await flushOutbox()
    expect(server.calls.map((c) => c.request_id)).toEqual([entry.id, entry.id])
    expect(outbox.entries).toEqual([])
  })

  it('a dead line stops the run with the rest still waiting', async () => {
    server.replay = async () => {
      throw new TypeError('Failed to fetch')
    }
    const offline = await load({ online: false })
    await offline.enqueue('create_task', { title: 'a' })
    await offline.enqueue('create_task', { title: 'b' })
    const { flushOutbox, outbox } = await load()
    await flushOutbox()
    expect(server.calls).toHaveLength(1)
    expect(outbox.entries.map((e) => e.status)).toEqual(['pending', 'pending'])
  })

  it('a refusal keeps the entry, with the server’s reason, and moves on', async () => {
    server.replay = async ({ payload }) => {
      if (payload.title === 'bad') throw refusal('This task is already done.')
      return { status: 'applied' }
    }
    const offline = await load({ online: false })
    const bad = await offline.enqueue('create_task', { title: 'bad' })
    await offline.enqueue('create_task', { title: 'good' })
    const { flushOutbox, outbox, rejectedCount, waitingCount } = await load()
    await flushOutbox()
    expect(server.calls).toHaveLength(2)
    expect(outbox.entries).toHaveLength(1)
    expect(outbox.entries[0]).toMatchObject({
      id: bad.id,
      status: 'rejected',
      error: 'This task is already done.',
    })
    expect(disk.get(bad.id).status).toBe('rejected')
    expect(rejectedCount.value).toBe(1)
    expect(waitingCount.value).toBe(0)
  })

  it('a lapsed session stops the run and refuses nothing', async () => {
    server.replay = async () => {
      throw Object.assign(new Error('expired'), {
        status: 403,
        exc_type: 'PermissionError',
        session_expired: 1,
      })
    }
    const { enqueue, flushOutbox, outbox } = await load()
    await enqueue('create_task', { title: 'x' })
    await flushOutbox()
    expect(outbox.entries[0].status).toBe('pending')
  })

  it('what was sent stays until a sync succeeds', async () => {
    server.syncOk = false
    const { enqueue, flushOutbox, outbox } = await load()
    await enqueue('create_task', { title: 'x' })
    await flushOutbox()
    expect(outbox.entries[0].status).toBe('sent')
    server.syncOk = true
    await flushOutbox()
    // not sent a second time: it only waited for the pack
    expect(server.calls).toHaveLength(1)
    expect(outbox.entries).toEqual([])
  })
})

describe('timing', () => {
  it('something captured while another entry is on the wire goes out in the same run', async () => {
    let release
    const { enqueue, flushOutbox, outbox } = await load()
    server.replay = async ({ payload }) => {
      if (payload.title === 'first') {
        await new Promise((resolve) => (release = resolve))
      }
      return { status: 'applied' }
    }
    await enqueue('create_task', { title: 'first' })
    await settle()
    await enqueue('create_task', { title: 'second' })
    release()
    await flushOutbox()
    expect(server.calls.map((c) => c.payload.title)).toEqual([
      'first',
      'second',
    ])
    expect(outbox.entries).toEqual([])
  })

  it('a pack sync that began before the send does not confirm it', async () => {
    server.syncOk = false
    const { enqueue, flushOutbox, outbox } = await load()
    await enqueue('create_task', { title: 'x' })
    await flushOutbox()
    const { backgroundSync } = await import('@/offline/pack')
    // the refresh that left before the replay: its pack cannot hold the entry
    backgroundSync(outbox.entries[0].sent_at - 1000)
    expect(outbox.entries.map((e) => e.status)).toEqual(['sent'])
    // one that began after does, whoever started it
    backgroundSync(outbox.entries[0].sent_at + 1)
    expect(outbox.entries).toEqual([])
  })

  it('something sent while the confirming sync was in flight gets a sync of its own', async () => {
    const { enqueue, flushOutbox, outbox } = await load()
    await enqueue('create_task', { title: 'first' })
    // lands after the first confirming download began
    const second = enqueue('create_task', { title: 'second' })
    await second
    await flushOutbox()
    await settle()
    expect(outbox.entries).toEqual([])
    expect(server.syncs).toBeGreaterThanOrEqual(1)
  })

  it('a refused entry sent again during a run is not left behind', async () => {
    let release
    let refuse = true
    server.replay = async ({ payload }) => {
      if (payload.title === 'slow') {
        await new Promise((resolve) => (release = resolve))
        return { status: 'applied' }
      }
      if (refuse) throw refusal('No.')
      return { status: 'applied' }
    }
    const { enqueue, flushOutbox, retryEntry, outbox } = await load()
    const bad = await enqueue('create_task', { title: 'bad' })
    await flushOutbox()
    expect(outbox.entries[0].status).toBe('rejected')
    refuse = false
    await enqueue('create_task', { title: 'slow' })
    await settle()
    const retried = retryEntry(bad.id)
    release()
    await retried
    expect(outbox.entries).toEqual([])
  })

  it('with nowhere to store it and no answer, the entry is kept and goes again under the same id', async () => {
    const { enqueue, flushOutbox, outbox } = await load()
    disk.set = () => {
      throw new Error('QuotaExceeded')
    }
    try {
      // the request left, the answer never came: the server may have it
      server.replay = async () => {
        throw Object.assign(new Error('Gateway Timeout'), { status: 504 })
      }
      const entry = await enqueue('create_task', { title: 'x' })
      expect(outbox.entries).toHaveLength(1)
      expect(outbox.entries[0].unsaved).toBe(true)
      server.replay = async () => ({ status: 'duplicate' })
      await flushOutbox()
      expect(server.calls.map((c) => c.request_id)).toEqual([
        entry.id,
        entry.id,
      ])
      expect(outbox.entries).toEqual([])
    } finally {
      delete disk.set
    }
  })

  it('an entry discarded while it is on the wire stays discarded', async () => {
    let release
    server.replay = () => new Promise((resolve) => (release = resolve))
    const { enqueue, flushOutbox, discardEntry, outbox } = await load()
    const entry = await enqueue('create_task', { title: 'x' })
    await settle()
    expect(outbox.entries[0].sending).toBe(true)
    await discardEntry(entry.id)
    release({ status: 'applied' })
    await flushOutbox()
    expect(outbox.entries).toEqual([])
    expect(disk.has(entry.id)).toBe(false)
  })
})

describe('coming back for what a server error left', () => {
  it('tries again within a minute, without the tab being hidden and shown', async () => {
    vi.useFakeTimers()
    try {
      server.replay = async () => {
        throw Object.assign(new Error('Bad Gateway'), { status: 502 })
      }
      const { enqueue, flushOutbox, startOutbox, outbox } = await load()
      startOutbox()
      await enqueue('create_task', { title: 'x' })
      await flushOutbox()
      expect(outbox.entries[0].status).toBe('pending')
      const before = server.calls.length
      server.replay = async () => ({ status: 'applied' })
      await vi.advanceTimersByTimeAsync(61000)
      expect(server.calls.length).toBe(before + 1)
      expect(outbox.entries).toEqual([])
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('the rep’s say', () => {
  it('a refused entry can be sent again or thrown away', async () => {
    server.replay = async () => {
      throw refusal('No.')
    }
    const { enqueue, flushOutbox, retryEntry, discardEntry, outbox } =
      await load()
    const entry = await enqueue('create_task', { title: 'x' })
    await flushOutbox()
    server.replay = async () => ({ status: 'applied' })
    await retryEntry(entry.id)
    expect(outbox.entries).toEqual([])

    server.replay = async () => {
      throw refusal('No.')
    }
    const other = await enqueue('create_task', { title: 'y' })
    await flushOutbox()
    await discardEntry(other.id)
    expect(outbox.entries).toEqual([])
    expect(disk.size).toBe(0)
  })

  it('another user’s entries are neither shown nor sent, and stay on the device', async () => {
    disk.set('theirs', {
      id: 'theirs',
      user: 'someone.else@example.com',
      action: 'create_task',
      payload: { title: 'not mine' },
      captured_at: 1,
      status: 'pending',
    })
    const { loadOutbox, flushOutbox, outbox } = await load()
    await loadOutbox()
    await flushOutbox()
    expect(outbox.entries).toEqual([])
    expect(server.calls).toEqual([])
    expect(disk.has('theirs')).toBe(true)
  })
})

const failure = (status, extra = {}) =>
  Object.assign(new Error(`HTTP ${status}`), {
    status,
    messages: ['Internal Server Error'],
    ...extra,
  })

const handshake = (message) =>
  vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ message }),
  }))

/* Runs of the outbox with the clock moved on between them: far enough that
   each failure falls in a window of its own. Only the date is faked, so the
   awaits inside a run still resolve. */
const WINDOW = 16 * 60 * 1000
async function spacedRuns(flushOutbox, runs) {
  for (let run = 0; run < runs; run++) {
    vi.setSystemTime(Date.now() + WINDOW)
    await flushOutbox()
  }
}
const fakeDate = () => vi.useFakeTimers({ toFake: ['Date'] })

const serverDown = () =>
  vi.fn(async () => ({ ok: false, status: 503, json: async () => null }))

describe('a stale CSRF token', () => {
  const staleUntilRenewed = async () => {
    if (window.csrf_token !== 'fresh') {
      throw failure(400, { exc_type: 'CSRFTokenError' })
    }
    return { status: 'applied' }
  }

  it('is renewed through the handshake, and the same entry goes again', async () => {
    const fetch = handshake({ user: 'rep@example.com', csrf_token: 'fresh' })
    vi.stubGlobal('fetch', fetch)
    window.csrf_token = 'the-old-sessions'
    server.replay = staleUntilRenewed
    const { enqueue, flushOutbox, outbox } = await load()
    const entry = await enqueue('create_task', { title: 'x' })
    await flushOutbox()
    expect(String(fetch.mock.calls[0][0])).toContain(
      'crm.api.offline.handshake',
    )
    expect(window.csrf_token).toBe('fresh')
    expect(server.calls.map((c) => c.request_id)).toEqual([entry.id, entry.id])
    expect(outbox.entries).toEqual([])
  })

  it('is asked for once a run, and the entry says to reload', async () => {
    const fetch = handshake({ user: 'rep@example.com', csrf_token: 'no-good' })
    vi.stubGlobal('fetch', fetch)
    window.csrf_token = 'the-old-sessions'
    server.replay = staleUntilRenewed
    const { enqueue, flushOutbox, outbox } = await load()
    await enqueue('create_task', { title: 'x' })
    await flushOutbox()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(server.calls).toHaveLength(2)
    expect(outbox.entries[0]).toMatchObject({ status: 'pending' })
    expect(outbox.entries[0].error).toMatch(/Reload the app/)
  })

  it('a renewal that could not be had leaves no reason behind', async () => {
    vi.stubGlobal('fetch', serverDown())
    window.csrf_token = 'the-old-sessions'
    server.replay = staleUntilRenewed
    const { enqueue, flushOutbox, outbox } = await load()
    await enqueue('create_task', { title: 'x' })
    await flushOutbox()
    expect(outbox.entries[0]).toMatchObject({ status: 'pending', error: null })
  })
})

describe('someone else signs in in another tab', () => {
  const OTHER = 'someone.else@example.com'

  it('what is typed on the first rep’s page is theirs, and is not sent as the other', async () => {
    // the page was loaded for the rep and shows the rep's customers
    const fetch = handshake({ user: OTHER, csrf_token: 'theirs' })
    vi.stubGlobal('fetch', fetch)
    window.csrf_token = 'the-reps'
    const { enqueue, flushOutbox, outbox, connectivity } = await load()
    // the cookie jar is shared: from here the cookie names the other user
    server.user = OTHER
    server.replay = async () => {
      throw failure(400, { exc_type: 'CSRFTokenError' })
    }
    const entry = await enqueue('add_note', { content: 'for my customer' })
    await flushOutbox()
    expect(entry.user).toBe('rep@example.com')
    expect(disk.get(entry.id).user).toBe('rep@example.com')
    expect(server.calls).toEqual([])
    expect(window.csrf_token).toBe('the-reps')
    expect(outbox.entries[0].status).toBe('pending')
    expect(connectivity.otherUser).toBe(true)
  })

  it('nor when the cookie has not caught up and only the server knows', async () => {
    const fetch = handshake({ user: OTHER, csrf_token: 'theirs' })
    vi.stubGlobal('fetch', fetch)
    window.csrf_token = 'the-reps'
    server.replay = async () => {
      if (window.csrf_token === 'theirs') return { status: 'applied' }
      throw failure(400, { exc_type: 'CSRFTokenError' })
    }
    const { enqueue, flushOutbox, outbox, connectivity } = await load()
    await enqueue('add_note', { content: 'for my customer' })
    await flushOutbox()
    await flushOutbox()
    // refused once with the old token, and never sent with theirs
    expect(server.calls).toHaveLength(1)
    expect(window.csrf_token).toBe('the-reps')
    expect(outbox.entries[0].status).toBe('pending')
    expect(connectivity.otherUser).toBe(true)
  })

  it('work captured as one rep is not sent on a session that is now another’s', async () => {
    const { enqueue, flushOutbox, outbox } = await load({ online: false })
    await enqueue('create_task', { title: 'mine' })
    const { connectivity } = await import('@/offline/connectivity')
    server.user = OTHER
    connectivity.online = true
    await flushOutbox()
    expect(server.calls).toEqual([])
    expect(outbox.entries[0].status).toBe('pending')
  })
})

describe('an answer the server did not write', () => {
  it('a bare 403 pauses the run and refuses nothing', async () => {
    // a captive portal at the site gate: it blocks the handshake as well
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status: 403, json: async () => null })),
    )
    server.replay = async () => {
      throw failure(403)
    }
    const offline = await load({ online: false })
    await offline.enqueue('create_task', { title: 'a' })
    await offline.enqueue('create_task', { title: 'b' })
    const { flushOutbox, outbox, rejectedCount, connectivity } = await load()
    await flushOutbox()
    expect(server.calls).toHaveLength(1)
    expect(outbox.entries.map((e) => e.status)).toEqual(['pending', 'pending'])
    expect(rejectedCount.value).toBe(0)
    // the probe found the server is not there: the app is offline, and that
    // is all the entry has to say
    expect(connectivity.online).toBe(false)
    expect(outbox.entries[0]).toMatchObject({ error: null })
    expect(outbox.entries[0].stalls ?? 0).toBe(0)
  })

  it('one entry a firewall will not pass does not hold the rest for ever', async () => {
    // the handshake gets through; this note's text does not
    server.replay = async ({ payload }) => {
      if (payload.title === 'blocked') throw failure(403)
      return { status: 'applied' }
    }
    const offline = await load({ online: false })
    const blocked = await offline.enqueue('create_task', { title: 'blocked' })
    await offline.enqueue('create_task', { title: 'fine' })
    fakeDate()
    const { flushOutbox, retryEntry, outbox, rejectedCount } = await load()
    await spacedRuns(flushOutbox, 4)
    expect(outbox.entries.map((e) => e.status)).toEqual(['pending', 'pending'])
    expect(outbox.entries[0].error).toMatch(/instead of the server/)
    await spacedRuns(flushOutbox, 1)
    expect(outbox.entries).toHaveLength(1)
    expect(outbox.entries[0]).toMatchObject({
      id: blocked.id,
      status: 'rejected',
    })
    expect(outbox.entries[0].error).toMatch(/set aside to let the rest go/)
    // sending it again cannot double it; typing it in again can
    expect(outbox.entries[0].error).toMatch(/Send again is safe/)
    expect(rejectedCount.value).toBe(1)
    expect(server.calls.at(-1).payload.title).toBe('fine')
    // and it can still be sent: nothing was thrown away
    server.replay = async () => ({ status: 'applied' })
    await retryEntry(blocked.id)
    expect(outbox.entries).toEqual([])
  })
})

describe('a server error at the head of the outbox', () => {
  it('stops the run in order, and the entry keeps the reason and the count', async () => {
    server.replay = async () => {
      throw failure(502)
    }
    const { enqueue, flushOutbox, outbox } = await load()
    const first = await enqueue('create_task', { title: 'one' })
    const second = await enqueue('create_task', { title: 'two' })
    await flushOutbox()
    await flushOutbox()
    const [a, b] = outbox.entries
    expect(server.calls.map((c) => c.request_id)).not.toContain(second.id)
    expect(a).toMatchObject({ id: first.id, status: 'pending' })
    expect(a.error).toBeTruthy()
    expect(a.attempts).toBeGreaterThan(1)
    expect(disk.get(first.id)).toMatchObject({
      status: 'pending',
      error: a.error,
      attempts: a.attempts,
    })
    expect(b).toMatchObject({ status: 'pending', error: null, attempts: 0 })
  })

  it('says what the server said, when it said something', async () => {
    server.replay = async () => {
      throw failure(500, {
        exc_type: 'QueryDeadlockError',
        messages: ['Deadlock found. Try again.'],
      })
    }
    const { enqueue, flushOutbox, outbox } = await load()
    await enqueue('create_task', { title: 'x' })
    await flushOutbox()
    expect(outbox.entries[0].error).toBe('Deadlock found. Try again.')
  })

  it('a dead line leaves no reason: that is the ordinary wait', async () => {
    server.replay = async () => {
      throw new TypeError('Failed to fetch')
    }
    const { enqueue, flushOutbox, outbox } = await load()
    await enqueue('create_task', { title: 'x' })
    await flushOutbox()
    expect(outbox.entries[0]).toMatchObject({ status: 'pending', error: null })
  })

  it('a reason kept from an earlier try goes when the line does', async () => {
    server.replay = async () => {
      throw failure(502)
    }
    const { enqueue, flushOutbox, outbox } = await load()
    const entry = await enqueue('create_task', { title: 'x' })
    await flushOutbox()
    expect(disk.get(entry.id).error).toBeTruthy()
    vi.stubGlobal('fetch', serverDown())
    await flushOutbox()
    expect(outbox.entries[0]).toMatchObject({ status: 'pending', error: null })
    expect(disk.get(entry.id).error).toBe(null)
  })

  it('the reason goes when the entry does', async () => {
    server.replay = async () => {
      throw failure(502)
    }
    const { enqueue, flushOutbox, outbox } = await load()
    await enqueue('create_task', { title: 'x' })
    await flushOutbox()
    server.syncOk = false
    server.replay = async () => ({ status: 'applied' })
    await flushOutbox()
    expect(outbox.entries[0]).toMatchObject({ status: 'sent', error: null })
  })

  it('the timer comes back less and less often while runs keep stopping', async () => {
    vi.useFakeTimers()
    try {
      server.replay = async () => {
        throw failure(502)
      }
      const { enqueue, flushOutbox, startOutbox } = await load()
      startOutbox()
      await enqueue('create_task', { title: 'x' })
      await flushOutbox()
      const sentBy = async (minutes) => {
        const before = server.calls.length
        await vi.advanceTimersByTimeAsync(minutes * 60 * 1000)
        return server.calls.length - before
      }
      // every minute at first, as before
      expect(await sentBy(1)).toBe(1)
      // then further apart: ten more minutes used to be ten more requests
      expect(await sentBy(10)).toBeLessThanOrEqual(3)
    } finally {
      vi.useRealTimers()
    }
  })

  it('looking at the tab, or the line coming back, does not jump the wait', async () => {
    vi.useFakeTimers()
    try {
      server.replay = async () => {
        throw failure(500, { exc_type: 'TypeError' })
      }
      const { enqueue, flushOutbox, startOutbox, outbox, connectivity } =
        await load()
      startOutbox()
      await enqueue('create_task', { title: 'x' })
      await flushOutbox()
      await flushOutbox()
      const before = server.calls.length
      // five tab switches and a reconnect inside the same minute
      for (let i = 0; i < 5; i++) {
        document.dispatchEvent(new Event('visibilitychange'))
        await vi.advanceTimersByTimeAsync(1000)
      }
      connectivity.online = false
      window.dispatchEvent(new Event('online'))
      await vi.advanceTimersByTimeAsync(1000)
      expect(server.calls.length).toBe(before)
      expect(outbox.entries[0].status).toBe('pending')
    } finally {
      vi.useRealTimers()
    }
  })

  it('five failures back to back are one failure seen five times: nothing is set aside', async () => {
    // replay is down for everyone while the handshake answers, and the rep
    // logs five things in a minute -- each one sets off a run
    server.replay = async () => {
      throw failure(500, { exc_type: 'TypeError' })
    }
    const { enqueue, flushOutbox, outbox, rejectedCount } = await load()
    for (const title of ['a', 'b', 'c', 'd', 'e']) {
      await enqueue('create_task', { title })
      await flushOutbox()
    }
    for (let run = 0; run < 5; run++) await flushOutbox()
    expect(server.calls.length).toBeGreaterThanOrEqual(5)
    expect(rejectedCount.value).toBe(0)
    expect(outbox.entries.map((e) => e.status)).toEqual(
      Array(5).fill('pending'),
    )
    expect(outbox.entries[0].stalls).toBe(1)
    // nothing passed the head, either
    expect(new Set(server.calls.map((c) => c.payload.title))).toEqual(
      new Set(['a']),
    )
  })

  it('an entry that fails in five windows running while the server answers is set aside, and the rest go', async () => {
    server.replay = async ({ payload }) => {
      if (payload.title === 'poison') {
        throw failure(500, { exc_type: 'TypeError' })
      }
      return { status: 'applied' }
    }
    const offline = await load({ online: false })
    const poison = await offline.enqueue('create_task', { title: 'poison' })
    await offline.enqueue('create_task', { title: 'fine' })
    fakeDate()
    const { flushOutbox, outbox, rejectedCount } = await load()
    await spacedRuns(flushOutbox, 4)
    // four windows: still at the head, still holding the one behind it
    expect(outbox.entries.map((e) => e.status)).toEqual(['pending', 'pending'])
    expect(outbox.entries[0].stalls).toBe(4)
    await spacedRuns(flushOutbox, 1)
    expect(outbox.entries).toHaveLength(1)
    expect(outbox.entries[0]).toMatchObject({
      id: poison.id,
      status: 'rejected',
    })
    expect(outbox.entries[0].error).toMatch(/set aside to let the rest go/)
    expect(rejectedCount.value).toBe(1)
    expect(server.calls.at(-1).payload.title).toBe('fine')
  })

  it('an outage is never held against the entries, whatever the server names', async () => {
    // redis is down: every request answers 500 with an exception, the
    // handshake included
    vi.stubGlobal('fetch', serverDown())
    server.replay = async () => {
      throw failure(500, { exc_type: 'ConnectionError' })
    }
    const offline = await load({ online: false })
    await offline.enqueue('create_task', { title: 'a' })
    await offline.enqueue('create_task', { title: 'b' })
    const { flushOutbox, outbox, connectivity } = await load()
    for (let run = 0; run < 8; run++) {
      // the rep keeps coming back to the tab; each time the app thinks it
      // may be online again
      connectivity.online = true
      await flushOutbox()
    }
    expect(outbox.entries.map((e) => e.status)).toEqual(['pending', 'pending'])
    expect(outbox.entries[0].stalls ?? 0).toBe(0)
    // and when it is over, both go
    vi.stubGlobal(
      'fetch',
      handshake({ user: 'rep@example.com', csrf_token: 'tok' }),
    )
    server.replay = async () => ({ status: 'applied' })
    connectivity.online = true
    await flushOutbox()
    expect(outbox.entries).toEqual([])
  })

  it('failures are counted in a row, per entry: a success in between starts again', async () => {
    let failing = true
    server.replay = async () => {
      if (failing) throw failure(500, { exc_type: 'TypeError' })
      return { status: 'applied' }
    }
    fakeDate()
    const { enqueue, flushOutbox, outbox, rejectedCount } = await load()
    await enqueue('create_task', { title: 'first' })
    await flushOutbox()
    await spacedRuns(flushOutbox, 3)
    expect(outbox.entries[0]).toMatchObject({ status: 'pending', stalls: 4 })
    // it gets through
    failing = false
    await spacedRuns(flushOutbox, 1)
    expect(outbox.entries).toEqual([])
    // the next one starts from nothing: four more failures set nothing aside
    failing = true
    await enqueue('create_task', { title: 'second' })
    await flushOutbox()
    await spacedRuns(flushOutbox, 3)
    expect(outbox.entries[0]).toMatchObject({ status: 'pending', stalls: 4 })
    expect(rejectedCount.value).toBe(0)
    // the fifth does, and Send again after that starts from nothing too
    await spacedRuns(flushOutbox, 1)
    expect(outbox.entries[0]).toMatchObject({ status: 'rejected', stalls: 0 })
  })

  it('a rate limit waits and is not held against the entry', async () => {
    server.replay = async () => {
      throw failure(429, { exc_type: 'TooManyRequestsError' })
    }
    const { enqueue, flushOutbox, outbox } = await load()
    await enqueue('create_task', { title: 'x' })
    for (let run = 0; run < 8; run++) await flushOutbox()
    expect(outbox.entries[0].status).toBe('pending')
    expect(outbox.entries[0].stalls ?? 0).toBe(0)
  })
})

describe('an entry older than the server’s memory of what it applied', () => {
  const DAY = 24 * 60 * 60 * 1000
  const old = () => ({
    id: 'ancient-entry-0001',
    user: 'rep@example.com',
    action: 'add_note',
    payload: { content: 'x' },
    captured_at: Date.now() - 91 * DAY,
    status: 'pending',
    error: null,
    attempts: 1,
  })

  it('is not sent on its own, and is kept for the rep with the reason', async () => {
    disk.set('ancient-entry-0001', old())
    const { flushOutbox, outbox } = await load()
    await flushOutbox()
    expect(server.calls).toEqual([])
    expect(outbox.entries[0]).toMatchObject({ status: 'rejected' })
    expect(outbox.entries[0].error).toMatch(/more than 90 days ago/)
    expect(disk.get('ancient-entry-0001').status).toBe('rejected')
  })

  it('goes to the server when the rep says so, which has the last word', async () => {
    disk.set('ancient-entry-0001', old())
    const { flushOutbox, retryEntry, outbox } = await load()
    await flushOutbox()
    server.replay = async () => ({ status: 'duplicate' })
    await retryEntry('ancient-entry-0001')
    expect(server.calls).toHaveLength(1)
    expect(outbox.entries).toEqual([])
  })

  it('one inside the window goes as usual', async () => {
    disk.set('ancient-entry-0001', {
      ...old(),
      captured_at: Date.now() - 89 * DAY,
    })
    const { flushOutbox } = await load()
    await flushOutbox()
    expect(server.calls).toHaveLength(1)
  })
})
