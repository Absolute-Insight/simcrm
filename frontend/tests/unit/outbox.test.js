import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * The outbox against a device (a map standing in for IndexedDB) and a server
 * that is told what to answer. Each test is a fresh page load.
 */
const { disk, server } = vi.hoisted(() => ({
  disk: new Map(),
  server: { replay: null, calls: [], syncs: 0, syncOk: true },
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
vi.mock('@/utils/session', () => ({ getSessionUser: () => 'rep@example.com' }))

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
  server.replay = async () => ({ status: 'applied' })
  vi.spyOn(document, 'cookie', 'get').mockReturnValue(
    'user_id=rep%40example.com',
  )
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
