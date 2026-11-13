import { clear } from 'idb-keyval'
import { clearBootSnapshot, OFFLINE_OWNER_KEY } from '@/offline/bootSnapshot'
import { packStore } from '@/offline/db'

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

const OWNER_KEY = OFFLINE_OWNER_KEY

/** The user this device's offline stores are claimed for, or null. */
export function offlineOwner() {
  try {
    return localStorage.getItem(OWNER_KEY)
  } catch {
    return null
  }
}

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
  // Field mode's copies go with it: the boot a cached shell starts from and
  // the pack of customers it shows. The outbox does not -- it is work the
  // server has not seen, and belongs to whoever typed it (offline/db.js).
  try {
    clearBootSnapshot(localStorage)
  } catch {
    // no storage, nothing kept
  }
  if (typeof indexedDB === 'undefined') return Promise.resolve()
  return Promise.all([
    clear().catch(() => {}),
    packStore.clear().catch(() => {}),
  ]).then(() => {})
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
