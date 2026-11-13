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
import {
  OUTBOX_MAX_AGE_DAYS,
  entryExpired,
  failureCause,
  newEntry,
  newEntryId,
} from '@/utils/fieldOutbox'
import { isSessionGone } from '@/utils/sessionExpiry'
import { getSessionUser } from '@/utils/session'
import {
  connectivity,
  onOnline,
  probe,
  renewToken,
  serverNow,
} from './connectivity'
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

const RETRY_PENDING_MS = 60 * 1000
/* How long the once-a-minute timer leaves a run that stopped on a failure,
   by how many runs in a row have: the next tick, then further apart. A server
   that is down is not helped by every phone asking it every minute. Anything
   the rep or the network does -- a new entry, Send again, coming back online,
   coming back to the tab -- still sends at once. */
const BACKOFF_MS = [0, 1, 3, 7, 15].map((minutes) => minutes * 60 * 1000)
/* The server itself failed on the same entry this many times: it is the
   entry, not the moment. It is set aside for the rep, as a refusal is, so
   the entries behind it are not held for ever. */
const FAULT_LIMIT = 5

let stalls = 0
let retryAt = 0

function stalled() {
  retryAt = Date.now() + BACKOFF_MS[Math.min(stalls, BACKOFF_MS.length - 1)]
  stalls += 1
}

function flowing() {
  stalls = 0
  retryAt = 0
}

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

/* Why an entry that is still waiting did not go, in words for the outbox
   screen. Text the server wrote for a person wins. No words for a dead line:
   that is the ordinary wait, and the screen already says there is no
   connection. */
function stallReason(cause, error, renewed) {
  if (cause === 'network') return null
  if (cause === 'token') {
    return renewed
      ? __('This device’s sign-in is out of date. Reload the app to send this.')
      : null
  }
  if (cause === 'between') {
    return __(
      'The connection here answered instead of the server. Check that this network lets you through.',
    )
  }
  return (
    describeError(error).message ||
    __('The server could not take this just now.')
  )
}

async function setAside(entry, reason) {
  entry.status = 'rejected'
  entry.error = reason
  await persist(entry).catch(() => {})
}

async function sendPending() {
  await loadOutbox()
  outbox.flushing = true
  const tried = new Set()
  let renewed = false
  let stopped = false
  try {
    // Asked again each time round, not listed once at the start: something
    // captured while the first entry was on the wire goes out in this run.
    for (;;) {
      if (!connectivity.online) break
      // Asked each time round as well. The cookie jar is shared between
      // tabs: if someone else has signed in since this page loaded, the
      // session is theirs, and work captured as one rep must not be applied
      // as another.
      const user = getSessionUser()
      const entry = outbox.entries.find(
        (other) =>
          other.status === 'pending' &&
          other.user === user &&
          !tried.has(other.id),
      )
      if (!entry) break
      tried.add(entry.id)
      if (!entry.expired && entryExpired(entry, serverNow())) {
        // The server keeps its record of what it applied for so long and no
        // longer: after that it cannot tell a retry from a new entry. Not
        // sent on the device's own initiative; "Send again" asks the server,
        // which answers "already have it" or refuses.
        entry.expired = true
        await setAside(
          entry,
          __(
            'This was captured more than {0} days ago, so it was not sent on its own. Send it again to check with the server, or discard it.',
            [OUTBOX_MAX_AGE_DAYS],
          ),
        )
        continue
      }
      entry.sending = true
      try {
        await send(entry)
      } catch (error) {
        entry.sending = false
        if (!held(entry)) continue
        if (isSessionGone(error, document.cookie)) break
        const cause = failureCause(error)
        if (cause === 'refused') {
          await setAside(entry, describeError(error).message)
          continue
        }
        if (cause === 'token' && !renewed) {
          // The page's token belongs to a session that is gone. Ask for
          // this session's and send the same entry again -- once a run: a
          // server that refuses the token it just issued is not fixed by
          // asking again.
          renewed = true
          if (await renewToken()) {
            tried.delete(entry.id)
            continue
          }
        }
        if (cause === 'fault') {
          entry.faults = (entry.faults ?? 0) + 1
          if (entry.faults >= FAULT_LIMIT) {
            await setAside(
              entry,
              __(
                'The server failed on this entry {0} times. Send it again, or report it and discard it.',
                [entry.faults],
              ),
            )
            continue
          }
        }
        // Something answered, and it was not the server: find out whether
        // the server is there at all. If the handshake is blocked too the
        // app goes offline, and comes back for this when the line does.
        if (cause === 'between') probe()
        // (no reason kept if the line itself went meanwhile: that is the
        // ordinary wait, and the reason would outlive its cause)
        entry.error = connectivity.online
          ? stallReason(cause, error, renewed)
          : null
        await persist(entry).catch(() => {})
        stopped = true
        break
      }
      entry.sending = false
      flowing()
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
    if (stopped) stalled()
  }
}

let sending = null

/**
 * Send what is waiting, oldest first, one at a time, then bring the pack up
 * to date. Never rejects.
 *
 * A refusal marks that entry and moves on. Anything else -- no network, a
 * server error, a lapsed session -- stops the run with the rest still
 * waiting, in order, because the next entry would hit the same thing; the
 * entry it stopped at keeps the reason, for the outbox screen.
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
  entry.faults = 0
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
  // A run that stopped on a server error leaves entries pending with the app
  // still "online", and nothing else would come back for them until the tab
  // was hidden and shown. Once a minute, while there is something to send --
  // and less often while runs keep stopping (BACKOFF_MS).
  setInterval(() => {
    if (!connectivity.online || document.visibilityState === 'hidden') return
    if (Date.now() < retryAt) return
    if (outbox.entries.some((entry) => entry.status === 'pending')) flush()
  }, RETRY_PENDING_MS)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && connectivity.online) {
      if (outbox.entries.some((e) => e.status !== 'rejected')) flush()
    }
  })
}
