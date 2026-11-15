/**
 * Whether the server can be reached, as the app actually experiences it.
 *
 * `navigator.onLine` answers a different question -- "is there a network
 * interface" -- and says yes on one bar of signal at a mine gate, where every
 * request then hangs. So "online" is earned: only a probe that comes back
 * makes it true, and only a probe that fails makes it false. A single request
 * that died is a reason to ask, not an answer: a laptop waking from sleep
 * drops one fetch and is back before the next click.
 *
 * The probe is `crm.api.offline.handshake`, which does three more jobs on the
 * way: it hands a shell that booted from the cache the session's CSRF token
 * (the cached page has none), it carries the server's clock, so a visit logged
 * offline can be stamped in time the server will agree with, and it says who
 * the session belongs to -- which a shell that picked its user from what was
 * on the device has to check before showing anything more.
 */
import { reactive } from 'vue'
import { isNetworkError } from '@/utils/describeError'
import { clearOfflineCache } from '@/utils/offlineCache'
import { redirectIfSessionGone } from '@/utils/sessionExpiry'
import { getSessionUser } from '@/utils/session'

const HANDSHAKE_URL = '/api/method/crm.api.offline.handshake'
const PROBE_TIMEOUT_MS = 8000
const RETRY_MS = [5000, 10000, 20000, 40000, 60000]
/* After a probe failed, requests fail at once for this long instead of each
   starting a probe of its own: a screen that keeps asking would otherwise keep
   the radio lit and make every request wait out the full timeout. */
const FAIL_FAST_MS = 4000
/* How long a navigation waits to learn whether the server is there before it
   settles for field mode. Short: on a dead line the alternative is a blank
   page, and the full app is one tap away once the probe does return. */
const NAVIGATION_PATIENCE_MS = 2500
/* The Jinja placeholder a page served raw still carries. frappe-ui skips it
   too. */
const UNRENDERED_TOKEN = '{{ csrf_token }}'

const shell = typeof window !== 'undefined' && !!window.__crm_offline_shell

/**
 * Who this page was loaded for, read once. `getSessionUser()` reads the live
 * cookie, and the cookie jar is shared between tabs: when someone else signs
 * in in another tab it names *them*, while this page still shows the first
 * person's week and customers. Whatever is written from this page -- an
 * outbox entry, the token its requests carry -- belongs to the person it was
 * loaded for, never to whoever the cookie names by then.
 */
export const pageUser =
  typeof document !== 'undefined' ? getSessionUser() : null

export const connectivity = reactive({
  /* A shell start is offline until the server says otherwise: the worker only
     serves the shell when the page itself could not be fetched. */
  online:
    !shell && (typeof navigator === 'undefined' || navigator.onLine !== false),
  /* This page is the cached shell, not one Frappe rendered. */
  shell,
  /* Server clock minus device clock, in ms; null until a handshake measured it. */
  skewMs: null,
  /* Where the person was going when offline sent them to field mode. */
  intended: null,
  /* The session is no longer `pageUser`'s: someone else signed in in another
     tab. This page must be reloaded before it sends anything more. */
  otherUser: false,
})

const onlineListeners = new Set()
let probing = null
let retryTimer = null
let attempt = 0
let lastFailureAt = 0
/* The server answered, and the answer was no: not signed in, or no sales
   role. Distinct from offline -- retrying will not change it. */
let refused = false
let leaving = false

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

function stopRetrying() {
  clearTimeout(retryTimer)
  retryTimer = null
  attempt = 0
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

function failed() {
  lastFailureAt = Date.now()
  connectivity.online = false
  scheduleRetry()
  return false
}

/**
 * What this device holds belongs to someone the server does not recognise as
 * the session's user. Empty it and load the real page, which will be the
 * login form, Not Permitted, or the app for whoever is signed in.
 *
 * Only a shell can get here. A page Frappe rendered was rendered for the
 * session's user; a shell chose its user from what was on the device.
 */
function handOver() {
  if (leaving) return
  leaving = true
  clearOfflineCache().then(() => window.location.reload())
}

async function runProbe({ renew = false } = {}) {
  // The browser is sure there is no network: believe it, and do not light up
  // the radio (or the console) with a request that cannot leave the device.
  // The reverse is not true -- "online" is only a claim, hence the request.
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    return failed()
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
      // Only Frappe's own refusal counts: it names the exception in a JSON
      // body. A 403 from something in between -- a proxy, a firewall page --
      // says nothing about the session, and must not empty a rep's pack at
      // the one moment it is needed. That is an unreachable server.
      const body = await response.json().catch(() => null)
      if (!body || !(body.exc_type || body.session_expired || body.exc)) {
        return failed()
      }
      // The server answered, so this is not an outage: the session lapsed
      // while the phone was away, or this user has no sales role.
      refused = true
      stopRetrying()
      setOnline(true)
      if (connectivity.shell) handOver()
      else redirectIfSessionGone({ status: response.status, ...body })
      return false
    }
    if (!response.ok) throw new Error(`handshake ${response.status}`)
    const { message } = await response.json()
    if (connectivity.shell && message?.user !== getSessionUser()) {
      // signed in, as somebody else: the pack on screen is not theirs
      refused = true
      stopRetrying()
      setOnline(true)
      handOver()
      return false
    }
    // A token is only ever taken for the person this page was loaded for.
    // Another user's, put behind this page's requests, would have the server
    // apply what is typed here -- under the first person's customers -- as
    // them.
    connectivity.otherUser = !!message?.user && message.user !== pageUser
    if (
      message?.csrf_token &&
      !connectivity.otherUser &&
      (renew || connectivity.shell || !hasToken())
    ) {
      window.csrf_token = message.csrf_token
    }
    if (Number.isFinite(message?.server_epoch)) {
      connectivity.skewMs = message.server_epoch * 1000 - Date.now()
    }
    refused = false
    stopRetrying()
    setOnline(true)
    return true
  } catch {
    return failed()
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

let renewing = null

/**
 * Ask for the session's CSRF token again and take it, whatever this page was
 * rendered with. For a request the server refused as `CSRFTokenError`: the
 * session was re-created under an open page (it lapsed overnight and the rep
 * signed in again in another tab), so the token Frappe inlined here is the
 * old session's and will be refused for as long as the page lives.
 *
 * Not what `probe()` does on its own: a page Frappe rendered keeps its token
 * unless the server has said that token is no good.
 * It never takes a token for anyone but `pageUser`: if the session is someone
 * else's now, this says no and `connectivity.otherUser` says why.
 * @returns {Promise<boolean>} true when the page now holds this user's current token
 */
export function renewToken() {
  renewing ||= (async () => {
    // not the answer of a probe already on its way: that one will not
    // replace a token the page already has
    if (probing) await probing.catch(() => {})
    probing = runProbe({ renew: true }).finally(() => {
      probing = null
    })
    return (await probing) && !connectivity.otherUser && hasToken()
  })().finally(() => {
    renewing = null
  })
  return renewing
}

function offlineError() {
  // Shaped like the browser's own, so describeError files it under 'offline'
  // and every page shows its offline state rather than a server error.
  const error = new TypeError('Failed to fetch')
  error.code = 'ERR_NETWORK'
  return error
}

function refusedError() {
  // the server's own shape for "not for you", so it reads as permission
  const error = new Error('Not permitted')
  error.status = 403
  error.exc_type = 'PermissionError'
  // ...and marked as this gate's, not the server's answer to the request
  error.gate = true
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
 * A request that dies on the way is not proof of anything. It starts a probe,
 * and the probe decides.
 *
 * @param {() => Promise<any>} send
 */
export async function throughGate(send) {
  if (!connectivity.online || (connectivity.shell && !hasToken())) {
    if (refused) throw refusedError()
    if (Date.now() - lastFailureAt < FAIL_FAST_MS) throw offlineError()
    const reached = await probe()
    if (refused) throw refusedError()
    if (!reached || !hasToken()) throw offlineError()
  }
  try {
    return await send()
  } catch (error) {
    if (isNetworkError(error)) probe()
    throw error
  }
}

/**
 * For the router: is the server there, as far as a navigation can afford to
 * find out? Online is yes. Otherwise ask, and wait a moment for the answer --
 * a slow line that does answer keeps the page the person asked for, and a dead
 * one costs them a couple of seconds, not a blank screen.
 * @returns {Promise<boolean>}
 */
export function reachableForNavigation() {
  if (connectivity.online) return Promise.resolve(true)
  if (refused || Date.now() - lastFailureAt < FAIL_FAST_MS) {
    return Promise.resolve(false)
  }
  return Promise.race([
    probe(),
    new Promise((resolve) =>
      setTimeout(() => resolve(false), NAVIGATION_PATIENCE_MS),
    ),
  ])
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
  window.addEventListener('online', () => {
    lastFailureAt = 0
    probe()
  })
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
