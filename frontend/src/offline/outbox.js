/**
 * The outbox on this device: work a rep did that the server has not seen yet.
 *
 * Everything the Field screens write goes through here, with a network or
 * without one. Online an entry is stored and sent in the same breath; offline
 * it is stored and waits. That is deliberate: the path that runs at a mine
 * with no signal is the path that runs every day in the office, so it is not
 * a branch nobody has exercised.
 *
 * An entry leaves the outbox in exactly two ways: the server confirmed it, or
 * the rep discarded it. Logout, a lapsed session and another user signing in
 * all leave it where it is (offline/db.js) -- it is the one store here that is
 * not a copy of something the server already has.
 */
import { computed, reactive } from 'vue'
import { call } from 'frappe-ui'
import { describeError } from '@/utils/describeError'
import { failureKind, newEntry, newEntryId } from '@/utils/fieldOutbox'
import { isSessionGone } from '@/utils/sessionExpiry'
import { getSessionUser } from '@/utils/session'
import { connectivity, onOnline, serverNow } from './connectivity'
import { hasIndexedDB, outboxStore } from './db'
import { packState, syncPack } from './pack'

export const outbox = reactive({
  /* This user's entries, oldest first. */
  entries: [],
  loaded: false,
  flushing: false,
})

/** Still to be sent. */
export const waitingCount = computed(
  () => outbox.entries.filter((entry) => entry.status === 'pending').length,
)
/** Refused by the server: each needs the rep to look at it. */
export const rejectedCount = computed(
  () => outbox.entries.filter((entry) => entry.status === 'rejected').length,
)

const byTime = (a, b) => a.captured_at - b.captured_at

async function persist(entry) {
  if (!hasIndexedDB()) throw new Error('no IndexedDB')
  // a plain copy: IndexedDB cannot clone a reactive proxy
  await outboxStore.set(entry.id, JSON.parse(JSON.stringify(entry)))
}

function forget(entry) {
  outbox.entries = outbox.entries.filter((other) => other.id !== entry.id)
  if (hasIndexedDB()) return outboxStore.del(entry.id).catch(() => {})
}

let loading = null

/** Read this user's entries from the device. Other users' stay untouched. */
export function loadOutbox() {
  loading ||= (async () => {
    const user = getSessionUser()
    try {
      const stored = hasIndexedDB() ? await outboxStore.entries() : []
      outbox.entries = stored
        .map(([, entry]) => entry)
        .filter((entry) => entry?.user === user && entry.id)
        .sort(byTime)
    } catch (error) {
      console.warn('outbox unavailable', error)
    } finally {
      outbox.loaded = true
    }
  })()
  return loading
}

/**
 * Capture one thing the rep did.
 *
 * Resolves once it is safely on the device -- not once it is sent. Rejects
 * only when it could be neither stored nor sent, which is the one case where
 * the rep must be told their work is not saved.
 */
export async function enqueue(action, payload) {
  await loadOutbox()
  const entry = newEntry(action, payload, {
    id: newEntryId(),
    user: getSessionUser(),
    capturedAt: serverNow(),
  })
  try {
    await persist(entry)
  } catch (error) {
    // Private mode, a full disk. Online it can still go straight out; offline
    // there is nowhere to keep it, and saying "saved" would be a lie.
    if (!connectivity.online) {
      throw new Error(
        __(
          'This device cannot save work offline. Connect and try again, or write it down.',
        ),
        { cause: error },
      )
    }
  }
  outbox.entries = [...outbox.entries, entry].sort(byTime)
  flushOutbox()
  return entry
}

async function send(entry) {
  entry.attempts += 1
  await call('crm.api.offline.replay', {
    request_id: entry.id,
    action: entry.action,
    payload: entry.payload,
    captured_at: entry.captured_at,
  })
}

let flushing = null

/**
 * Send what is waiting, oldest first, one at a time. Never rejects.
 *
 * A refusal marks that entry and moves on. Anything else -- no network, a
 * server error, a lapsed session -- stops the run with the rest still
 * waiting, because the next entry would hit the same thing.
 */
export function flushOutbox() {
  flushing ||= (async () => {
    await loadOutbox()
    outbox.flushing = true
    let sentAny = false
    try {
      for (const entry of outbox.entries.filter(
        (e) => e.status === 'pending',
      )) {
        if (!connectivity.online) break
        try {
          await send(entry)
        } catch (error) {
          if (isSessionGone(error, document.cookie)) break
          if (failureKind(error) !== 'rejected') break
          entry.status = 'rejected'
          entry.error = describeError(error).message
          await persist(entry).catch(() => {})
          continue
        }
        // Applied, or already applied by an earlier attempt whose answer was
        // lost. Kept as `sent` so the screens go on showing it until a sync
        // brings the server's own version of the same thing.
        entry.status = 'sent'
        entry.error = null
        sentAny = true
        await persist(entry).catch(() => {})
      }
    } finally {
      outbox.flushing = false
    }
    if (sentAny || outbox.entries.some((e) => e.status === 'sent')) {
      await confirmSent()
    }
  })().finally(() => {
    flushing = null
  })
  return flushing
}

/** After a sync, what was sent is in the pack itself: the overlay can go. */
async function confirmSent() {
  if (!(await syncPack())) return
  for (const entry of outbox.entries.filter((e) => e.status === 'sent')) {
    await forget(entry)
  }
}

/** Give a refused entry another go, after the rep has read why. */
export async function retryEntry(id) {
  const entry = outbox.entries.find((other) => other.id === id)
  if (!entry || entry.status !== 'rejected') return
  entry.status = 'pending'
  entry.error = null
  await persist(entry).catch(() => {})
  return flushOutbox()
}

/** Throw an entry away. The only way one leaves without the server's say. */
export function discardEntry(id) {
  const entry = outbox.entries.find((other) => other.id === id)
  if (entry) return forget(entry)
}

let started = false

/** Send on start and whenever the server comes back. Idempotent. */
export function startOutbox() {
  if (started || !getSessionUser()) return
  started = true
  const flush = () => {
    if (!packState.refused) flushOutbox()
  }
  loadOutbox().then(() => {
    if (connectivity.online && outbox.entries.length) flush()
  })
  onOnline(flush)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && connectivity.online) {
      if (outbox.entries.some((e) => e.status !== 'rejected')) flush()
    }
  })
}
