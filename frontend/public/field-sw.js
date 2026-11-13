/*
 * Imported by the generated service worker (vite.config.js: workbox.importScripts).
 *
 * One job: when a navigation to the app cannot reach the server, answer it
 * with the precached shell instead of the browser's "no internet" page.
 *
 * Network first, always. The real page carries the session's boot and CSRF
 * token and must come from Frappe whenever Frappe can be reached; the shell is
 * the fallback, not a faster path. The timeout is for the connection that is
 * technically there -- one bar at a mine gate -- where a navigation otherwise
 * spins for a minute before failing.
 *
 * Registered before workbox's own listeners (importScripts runs first), so
 * this handler answers navigations and everything else falls through to the
 * precache routes untouched.
 */
const SHELL_URL = new URL('shell.html', self.location.href).href
const NAVIGATION_TIMEOUT_MS = 6000

function isAppNavigation(request) {
  if (request.mode !== 'navigate' || request.method !== 'GET') return false
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return false
  // The worker's scope is the prefix "/crm", which also matches /crm-form/:
  // the public web form is not this app and gets no shell.
  return url.pathname === '/crm' || url.pathname.startsWith('/crm/')
}

async function navigate(request) {
  // ignoreSearch: workbox stores it as shell.html?__WB_REVISION__=<hash>
  const shell = await caches.match(SHELL_URL, { ignoreSearch: true })
  if (!shell) return fetch(request)

  const network = fetch(request).catch(() => null)
  const timeout = new Promise((resolve) =>
    setTimeout(() => resolve(null), NAVIGATION_TIMEOUT_MS),
  )
  return (await Promise.race([network, timeout])) || shell
}

self.addEventListener('fetch', (event) => {
  if (isAppNavigation(event.request)) event.respondWith(navigate(event.request))
})
