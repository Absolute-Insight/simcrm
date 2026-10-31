import { clear } from 'idb-keyval'

/**
 * frappe-ui keeps the last response of every `cache:` resource in IndexedDB
 * (idb-keyval's store) and replays it into the resource on the next page load,
 * before the server has answered. The key is the resource's cache key, with no
 * user in it, and nothing ever cleared the store: on a shared browser the next
 * person to log in was shown the previous rep's leads and timelines until their
 * own response arrived, and the copy stayed on disk after logout.
 *
 * So the store belongs to one user. It is cleared on logout and when the
 * session is lost, and when a page loads for anyone other than the user who
 * last claimed it -- which covers a logout from the desk, or a session that
 * simply expired, where this app never got the chance to clear it.
 */

const OWNER_KEY = 'crm-offline-cache-owner'

/**
 * Empty the store and forget its owner, so the next load starts clean even
 * for the same user (a response still in flight can land after the clear).
 * Never rejects: callers chain a redirect onto it.
 */
export function clearOfflineCache() {
  try {
    localStorage.removeItem(OWNER_KEY)
  } catch {
    // no storage: claimOfflineCache clears on every load instead
  }
  if (typeof indexedDB === 'undefined') return Promise.resolve()
  return clear().catch(() => {})
}

/**
 * Clear the store unless `user` is the one who last claimed it, then claim it.
 *
 * Must run before any cached resource is created: idb-keyval queues its
 * requests in call order, so a clear issued first is done before any replay
 * reads the store.
 */
export function claimOfflineCache(user) {
  let owner = null
  try {
    owner = localStorage.getItem(OWNER_KEY)
  } catch {
    // unreadable: treat the store as someone else's
  }
  if (user && owner === user) return Promise.resolve()
  const cleared = clearOfflineCache()
  try {
    if (user) localStorage.setItem(OWNER_KEY, user)
  } catch {
    // not remembered: the next load clears again, which is the safe side
  }
  return cleared
}
