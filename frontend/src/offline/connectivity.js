/**
 * Whether the server can be reached, as the app actually experiences it.
 *
 * `navigator.onLine` answers a different question -- "is there a network
 * interface" -- and says yes on one bar of signal at a mine gate, where every
 * request then hangs. So the answer here is earned: a request that fails the
 * way an unreachable server fails marks the app offline, and only a probe that
 * comes back marks it online again.
 *
 * The probe is `crm.api.offline.handshake`, which does two more jobs on the
 * way: it hands a shell that booted from the cache the session's CSRF token
 * (the cached page has none), and it carries the server's clock, so a visit
 * logged offline can be stamped in time the server will agree with.
 */
import { reactive } from 'vue'
import { isNetworkError } from '@/utils/describeError'
import { redirectIfSessionGone } from '@/utils/sessionExpiry'

const HANDSHAKE_URL = '/api/method/crm.api.offline.handshake'
const PROBE_TIMEOUT_MS = 8000
const RETRY_MS = [5000, 10000, 20000, 40000, 60000]
/* The Jinja placeholder a page served raw still carries. frappe-ui skips it
   too. */
const UNRENDERED_TOKEN = '{{ csrf_token }}'

const shell = typeof window !== 'undefined' && !!window.__crm_offline_shell

export const connectivity = reactive({
  /* A shell start is offline until the server says otherwise: the worker only
     serves the shell when the page itself could not be fetched. */
  online:
    !shell && (typeof navigator === 'undefined' || navigator.onLine !== false),
  /* This page is the cached shell, not one Frappe rendered. */
  shell,
  /* Server clock minus device clock, in ms; null until a handshake measured it. */
  skewMs: null,
})

const onlineListeners = new Set()
let probing = null
let retryTimer = null
let attempt = 0

/** Run `fn` each time the server becomes reachable again. Returns an unsubscribe. */
export function onOnline(fn) {
  onlineListeners.add(fn)
  return () => onlineListeners.delete(fn)
}

function hasToken() {
  return !!window.csrf_token && window.csrf_token !== UNRENDERED_TOKEN
}

function setOnline(value) {
  if (connectivity.online === value) return
  connectivity.online = value
  if (!value) return
  for (const fn of onlineListeners) {
    try {
      fn()
    } catch (error) {
      console.error('onOnline listener failed', error)
    }
  }
}

function scheduleRetry() {
  if (retryTimer || connectivity.online) return
  const delay = RETRY_MS[Math.min(attempt, RETRY_MS.length - 1)]
  attempt += 1
  retryTimer = setTimeout(() => {
    retryTimer = null
    // a hidden tab waits for visibilitychange instead of waking the radio
    if (document.visibilityState === 'hidden') return
    probe()
  }, delay)
}

async function runProbe() {
  // The browser is sure there is no network: believe it, and do not light up
  // the radio (or the console) with a request that cannot leave the device.
  // The reverse is not true -- "online" is only a claim, hence the request.
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    connectivity.online = false
    scheduleRetry()
    return false
  }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS)
  try {
    const response = await fetch(HANDSHAKE_URL, {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
        'X-Frappe-Site-Name': window.location.hostname,
      },
      signal: controller.signal,
    })
    if (response.status === 401 || response.status === 403) {
      // The server answered, so this is not an outage: the session lapsed
      // while the phone was away, or the user has no sales role.
      setOnline(true)
      redirectIfSessionGone({ status: response.status })
      return false
    }
    if (!response.ok) throw new Error(`handshake ${response.status}`)
    const { message } = await response.json()
    if (message?.csrf_token && (connectivity.shell || !hasToken())) {
      window.csrf_token = message.csrf_token
    }
    if (Number.isFinite(message?.server_epoch)) {
      connectivity.skewMs = message.server_epoch * 1000 - Date.now()
    }
    attempt = 0
    setOnline(true)
    return true
  } catch {
    connectivity.online = false
    scheduleRetry()
    return false
  } finally {
    clearTimeout(timer)
  }
}

/**
 * Ask the server whether it is there. One request at a time: callers that
 * arrive while one is in flight share its answer.
 * @returns {Promise<boolean>} true when the server answered and the session is good
 */
export function probe() {
  probing ||= runProbe().finally(() => {
    probing = null
  })
  return probing
}

function offlineError() {
  // Shaped like the browser's own, so describeError files it under 'offline'
  // and every page shows its offline state rather than a server error.
  const error = new TypeError('Failed to fetch')
  error.code = 'ERR_NETWORK'
  return error
}

/**
 * Send a request through the connectivity gate.
 *
 * Offline, the request is not attempted until a probe gets through: on a
 * dead-slow line a fetch hangs for a minute before failing, and a page full of
 * them is a page full of spinners. A shell with no CSRF token waits for the
 * handshake for the same reason a POST without one would be refused.
 *
 * @param {() => Promise<any>} send
 */
export async function throughGate(send) {
  if (!connectivity.online || (connectivity.shell && !hasToken())) {
    const reached = await probe()
    if (!reached || !hasToken()) throw offlineError()
  }
  try {
    return await send()
  } catch (error) {
    if (isNetworkError(error)) {
      connectivity.online = false
      scheduleRetry()
    }
    throw error
  }
}

/** Server time now, as ms since the epoch, corrected for this device's clock. */
export function serverNow() {
  return Date.now() + (connectivity.skewMs ?? 0)
}

let watching = false

/** Listen for the browser's own hints. Idempotent; main.js calls it once. */
export function watchConnectivity() {
  if (watching || typeof window === 'undefined') return
  watching = true
  window.addEventListener('online', () => probe())
  window.addEventListener('offline', () => {
    connectivity.online = false
  })
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && !connectivity.online) probe()
  })
  // Offline, every resource the app shell creates on boot rejects, and most
  // have nobody waiting on them: a wall of "Uncaught (in promise) TypeError:
  // Failed to fetch". That is the expected state here, not a fault, and the
  // screens that care read their resource's own error. Anything that is not a
  // dead network still reaches the console.
  window.addEventListener('unhandledrejection', (event) => {
    if (!connectivity.online && isNetworkError(event.reason)) {
      event.preventDefault()
    }
  })
  if (connectivity.shell || !connectivity.online) probe()
}
