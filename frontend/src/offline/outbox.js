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
import { onPackSynced, packState, syncPackFresh } from './pack'

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
 * Resolves once it is safe -- on the device, or failing that on the server.
 * Rejects when it is neither, which is the one case where the rep must be
 * told their work is not saved.
 */
export async function enqueue(action, payload) {
  await loadOutbox()
  const entry = newEntry(action, payload, {
    id: newEntryId(),
    user: getSessionUser(),
    capturedAt: serverNow(),
  })
  let stored = true
  try {
    await persist(entry)
  } catch {
    stored = false
  }
  // Private mode, a full disk: nowhere to keep it. Offline that is the end of
  // it, and saying "saved" would be a lie.
  if (!stored && !connectivity.online) throw unsavedError()

  outbox.entries = [...outbox.entries, entry].sort(byTime)
  const live = () => outbox.entries.find((other) => other.id === entry.id)
  if (stored) {
    flushOutbox()
    return entry
  }
  // Not on the device, so "saved" has to mean the server has it.
  await flushOutbox()
  const now = live()
  if (!now || now.status === 'sent') return entry
  if (now.status === 'rejected' || now.attempts === 0) {
    outbox.entries = outbox.entries.filter((other) => other.id !== entry.id)
    throw now.status === 'rejected' ? new Error(now.error) : unsavedError()
  }
  // Sent, and no answer: the server may well have it. Taking it back here
  // would have the rep type it again under a new id, and then it is there
  // twice. It stays, in memory only, and goes again under the same id for as
  // long as this page is open.
  now.unsaved = true
  return entry
}

function unsavedError() {
  return new Error(
    __(
      'This device cannot save work offline. Connect and try again, or write it down.',
    ),
  )
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

/* Still in the outbox? A rep can discard an entry while it is on the wire;
   what comes back must not write it onto the device again. */
const held = (entry) => outbox.entries.some((other) => other.id === entry.id)

async function sendPending() {
  await loadOutbox()
  outbox.flushing = true
  const tried = new Set()
  try {
    // Asked again each time round, not listed once at the start: something
    // captured while the first entry was on the wire goes out in this run.
    for (;;) {
      if (!connectivity.online) break
      const entry = outbox.entries.find(
        (other) => other.status === 'pending' && !tried.has(other.id),
      )
      if (!entry) break
      tried.add(entry.id)
      entry.sending = true
      try {
        await send(entry)
      } catch (error) {
        entry.sending = false
        if (!held(entry)) continue
        if (isSessionGone(error, document.cookie)) break
        if (failureKind(error) !== 'rejected') break
        entry.status = 'rejected'
        entry.error = describeError(error).message
        await persist(entry).catch(() => {})
        continue
      }
      entry.sending = false
      if (!held(entry)) continue
      // Applied, or already applied by an earlier attempt whose answer was
      // lost. Kept as `sent` so the screens go on showing it until a sync
      // that began after this moment brings the server's own version.
      entry.status = 'sent'
      entry.sent_at = Date.now()
      entry.error = null
      await persist(entry).catch(() => {})
    }
  } finally {
    outbox.flushing = false
  }
}

let sending = null

/**
 * Send what is waiting, oldest first, one at a time, then bring the pack up
 * to date. Never rejects.
 *
 * A refusal marks that entry and moves on. Anything else -- no network, a
 * server error, a lapsed session -- stops the run with the rest still
 * waiting, because the next entry would hit the same thing.
 */
export function flushOutbox() {
  sending ||= sendPending().finally(() => {
    sending = null
  })
  return sending.then(confirmSent).catch((error) => {
    console.error('outbox flush failed', error)
  })
}

/* What was sent is in the pack once a sync that *started after the send*
   has stored one. Asked of every pack sync, whoever started it: the
   background refresh confirms an entry as well as the one requested here. */
function dropConfirmed(syncStartedAt) {
  for (const entry of outbox.entries) {
    if (entry.status === 'sent' && (entry.sent_at ?? 0) <= syncStartedAt) {
      forget(entry)
    }
  }
}
onPackSynced(dropConfirmed)

let confirming = null

/* One at a time: every caller of flushOutbox arrives here, and two of them
   must not each download a pack to confirm the same entry. */
function confirmSent() {
  confirming ||= (async () => {
    const waiting = () =>
      connectivity.online &&
      outbox.entries.some((entry) => entry.status === 'sent')
    // Twice at most: something sent while the first download was in flight
    // is not in it, and would otherwise wait for the ten-minute refresh.
    for (let round = 0; round < 2 && waiting(); round++) {
      if (!(await syncPackFresh())) break
    }
  })().finally(() => {
    confirming = null
  })
  return confirming
}

/** Give a refused entry another go, after the rep has read why. */
export async function retryEntry(id) {
  const entry = outbox.entries.find((other) => other.id === id)
  if (!entry || entry.status !== 'rejected') return
  entry.status = 'pending'
  entry.error = null
  await persist(entry).catch(() => {})
  // a run already under way has been past this entry once and will not look
  // at it again: let it finish, then start one that will
  if (sending) await sending.catch(() => {})
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
