/**
 * The two IndexedDB stores field mode keeps, apart from frappe-ui's resource
 * cache (idb-keyval's default store) and from each other, because they are
 * emptied on different occasions:
 *
 * - the **pack** is a copy of server data. It goes whenever the device may be
 *   changing hands: logout, a lost session, another user (utils/offlineCache).
 * - the **outbox** is work a rep typed that the server has not seen. Nothing
 *   clears it but a successful sync or the rep discarding an entry.
 *
 * idb-keyval gives one object store per database, hence two databases. They
 * are opened on first use: importing this file must not touch indexedDB, which
 * main.js's first import and the unit tests both rely on.
 */
import { clear, createStore, del, entries, get, set } from 'idb-keyval'

function lazyStore(database, name) {
  let store
  // Opening can throw outright (no IndexedDB, a blocked database). Callers
  // chain `.catch` on these, so the failure has to arrive as a rejection.
  const using = (run) => {
    try {
      return run((store ||= createStore(database, name)))
    } catch (error) {
      return Promise.reject(error)
    }
  }
  return {
    get: (key) => using((s) => get(key, s)),
    set: (key, value) => using((s) => set(key, value, s)),
    del: (key) => using((s) => del(key, s)),
    entries: () => using((s) => entries(s)),
    clear: () => using((s) => clear(s)),
  }
}

export const packStore = lazyStore('vectora-field-pack', 'pack')
export const outboxStore = lazyStore('vectora-field-outbox', 'outbox')
/* The photos and recordings on outbox entries, as Blobs, keyed by the id the
   entry's payload names them by. A store of its own so the outbox entries stay
   small enough to load and sort as they are; emptied with its entry. */
export const mediaStore = lazyStore('vectora-field-media', 'media')

export function hasIndexedDB() {
  return typeof indexedDB !== 'undefined'
}
