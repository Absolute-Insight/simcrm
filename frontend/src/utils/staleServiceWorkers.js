/**
 * Retire the service worker registrations a scope change leaves behind.
 *
 * A registration is keyed by its scope, so moving the worker from
 * `/assets/crm/frontend/` (vite's base, which vite-plugin-pwa used to derive
 * the scope from) to `/crm` (where Frappe actually serves the app) does not
 * move the old registration -- it creates a second one alongside it. The old
 * one stays installed, controls no pages, and holds its precache: several MB
 * of Cache Storage that nothing will ever read, kept alive because its script
 * URL still resolves.
 *
 * Unregistering does not drop the caches, so both have to be swept, and the
 * cache names are the only handle on which caches belonged to which scope --
 * workbox builds them as `workbox-precache-v2-<registration.scope>`.
 *
 * The selectors are separated from the browser calls so the interesting part
 * -- which things are stale -- is testable without a ServiceWorkerContainer.
 */

const pathnameOf = (url) => {
  try {
    // Registration scopes and script URLs are absolute; the base only matters
    // for the relative values tests find it convenient to write.
    return new URL(url, 'https://scope.invalid').pathname
  } catch {
    return null
  }
}

const scriptUrlsOf = (registration) =>
  [registration.installing, registration.waiting, registration.active]
    .filter(Boolean)
    .map((worker) => worker.scriptURL)
    .filter(Boolean)

/**
 * Registrations for *our* worker sitting at a scope we no longer use.
 *
 * The script check is not a formality: this origin is shared with Frappe's
 * desk and website, and unregistering a worker some other app installed is
 * not ours to do. Matching on the script we ship keeps the sweep to our own.
 */
export function selectSupersededRegistrations(
  registrations,
  { scriptPath, scope },
) {
  const wanted = pathnameOf(scope)
  return registrations.filter((registration) => {
    const isOurs = scriptUrlsOf(registration).some(
      (url) => pathnameOf(url) === scriptPath,
    )
    return isOurs && pathnameOf(registration.scope) !== wanted
  })
}

/**
 * Caches named after a scope we just retired.
 *
 * `currentScope` is not belt-and-braces. Scopes nest: a later move from `/crm`
 * to `/crm/app` would make the retired scope a substring of the live one, and
 * a plain `includes` would then delete the running worker's precache. The live
 * scope wins every tie.
 */
export function selectOrphanedCaches(
  cacheNames,
  { supersededScopes, currentScope },
) {
  return cacheNames.filter((name) => {
    if (currentScope && name.includes(currentScope)) return false
    return supersededScopes.some((scope) => scope && name.includes(scope))
  })
}

/**
 * Run the sweep. Resolves either way -- this is housekeeping, and a browser
 * that refuses (private mode, storage disabled, no ServiceWorkerContainer)
 * should cost the app nothing.
 */
export async function cleanUpSupersededWorkers({ scriptPath, scope }) {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) {
    return []
  }

  try {
    const registrations = await navigator.serviceWorker.getRegistrations()
    const superseded = selectSupersededRegistrations(registrations, {
      scriptPath,
      scope,
    })
    if (!superseded.length) return []

    const supersededScopes = superseded.map((r) => r.scope)
    await Promise.all(superseded.map((r) => r.unregister()))

    if (typeof caches !== 'undefined') {
      const orphaned = selectOrphanedCaches(await caches.keys(), {
        supersededScopes,
        currentScope: new URL(scope, location.origin).href,
      })
      await Promise.all(orphaned.map((name) => caches.delete(name)))
    }

    return supersededScopes
  } catch {
    return []
  }
}
