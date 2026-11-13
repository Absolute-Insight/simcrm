/**
 * The field pack on this device: loading it, keeping it fresh, dropping it.
 *
 * The pack is a snapshot of what the signed-in rep may see (crm/api/offline.py)
 * held in IndexedDB so the Field screens have something to show with no
 * network. It is the same object online and offline -- the screens never read
 * the server directly -- so the offline path is the one exercised every day,
 * not a branch that only runs at a mine.
 */
import { reactive, shallowRef } from 'vue'
import { call } from 'frappe-ui'
import { isMobileView } from '@/composables/settings'
import { offlineOwner } from '@/utils/offlineCache'
import { getSessionUser } from '@/utils/session'
import { packExpired } from '@/utils/fieldPack'
import { connectivity, onOnline } from './connectivity'
import { hasIndexedDB, packStore } from './db'
import { dropUnlistedSheets, forgetSavedSheets } from './sheets'

const PACK_KEY = 'pack'
/* Background refreshes are no closer together than this. A rep's customers do
   not change by the minute, and the phone is often on a metered line. */
const REFRESH_MS = 10 * 60 * 1000
const FIELD_USED_KEY = 'crm-field-mode-used'

/** The pack itself, or null when this device holds none. Replaced, never mutated. */
export const fieldPack = shallowRef(null)

export const packState = reactive({
  /* IndexedDB has been read: `fieldPack` null now means "nothing saved". */
  loaded: false,
  syncing: false,
  /* Device time (ms) of the last successful sync. */
  syncedAt: null,
  /* The last sync's failure, cleared by the next success. */
  error: null,
  /* The pack's shelf life in days, as the server set it. */
  maxAgeDays: null,
  /* The server refused: this user has no sales role. Stop asking. */
  refused: false,
})

let loading = null

/**
 * Read the stored pack into `fieldPack`. A pack for someone else, or one past
 * its shelf life, is deleted rather than shown.
 */
export function loadPack() {
  loading ||= (async () => {
    const user = getSessionUser()
    try {
      const stored = hasIndexedDB() ? await packStore.get(PACK_KEY) : null
      if (
        stored &&
        stored.pack?.user === user &&
        !packExpired(stored.syncedAt, stored.pack?.max_age_days)
      ) {
        fieldPack.value = stored.pack
        packState.syncedAt = stored.syncedAt
        packState.maxAgeDays = stored.pack.max_age_days
      } else if (stored) {
        // the whole store, not the one key: the sheets kept beside the pack
        // are the same user's and the same age
        await packStore.clear()
        forgetSavedSheets()
      }
    } catch (error) {
      // private mode or a blocked database: field mode works online only
      console.warn('field pack unavailable', error)
    } finally {
      packState.loaded = true
    }
  })()
  return loading
}

let syncing = null
const syncedListeners = new Set()

/**
 * Run `fn(startedAt)` after each sync that stored a pack, with the device
 * time that sync *began*: whatever reached the server before then is in it.
 */
export function onPackSynced(fn) {
  syncedListeners.add(fn)
  return () => syncedListeners.delete(fn)
}

/**
 * Fetch the pack and store it. Resolves to true when the device now holds a
 * current pack; never rejects -- the failure is on `packState.error`, where
 * the screens read it.
 */
export function syncPack() {
  syncing ||= (async () => {
    await loadPack()
    packState.syncing = true
    const user = getSessionUser()
    const startedAt = Date.now()
    try {
      const answer = await call('crm.api.offline.get_pack', {
        known_hash: fieldPack.value?.hash || undefined,
      })
      // A sync that outlived a logout must not write the old user's rows back.
      // The owner key is what a logout clears, in a shell too -- where the
      // session user is read from the page and would still say the old name.
      if (
        answer.user !== user ||
        answer.user !== getSessionUser() ||
        offlineOwner() !== user
      ) {
        return false
      }
      const syncedAt = Date.now()
      const pack = answer.unchanged
        ? {
            ...fieldPack.value,
            generated_at: answer.generated_at,
            today: answer.today,
          }
        : answer
      fieldPack.value = pack
      packState.syncedAt = syncedAt
      packState.maxAgeDays = pack.max_age_days
      packState.error = null
      if (hasIndexedDB()) {
        await packStore.set(PACK_KEY, { pack, syncedAt }).catch((error) => {
          // over quota: the pack is still good for this session
          console.warn('field pack not stored', error)
        })
      }
      for (const fn of syncedListeners) fn(startedAt)
      // only on a pack that carries the list: an "unchanged" answer keeps the
      // old one, and a pack from before sheets existed has none to compare
      if (Array.isArray(pack.sheets)) {
        dropUnlistedSheets(pack.sheets.map((sheet) => sheet.name)).catch(
          () => {},
        )
      }
      return true
    } catch (error) {
      packState.error = error
      if (error?.exc_type === 'PermissionError') packState.refused = true
      return false
    } finally {
      packState.syncing = false
    }
  })().finally(() => {
    syncing = null
  })
  return syncing
}

/**
 * A sync that starts now. `syncPack` shares one already in flight, which is
 * right for "keep it fresh" and wrong for "show me what I just sent": that
 * one may have left before the send did.
 */
export async function syncPackFresh() {
  if (syncing) await syncing
  return syncPack()
}

function due() {
  if (packState.refused || !connectivity.online) return false
  if (document.visibilityState === 'hidden') return false
  // a little under the interval: the timer that asks fires every REFRESH_MS,
  // and a sync stamped just after one tick must not be skipped by the next
  return (
    !packState.syncedAt || Date.now() - packState.syncedAt > REFRESH_MS * 0.9
  )
}

/**
 * Drop a pack that has outlived its shelf life while the app stayed open.
 * loadPack checks once, at start; a phone left on Field for a fortnight with
 * no signal would otherwise show its customers for as long as it stayed open.
 */
export function dropExpiredPack() {
  if (!fieldPack.value) return
  if (!packExpired(packState.syncedAt, packState.maxAgeDays)) return
  fieldPack.value = null
  packState.syncedAt = null
  forgetSavedSheets()
  if (hasIndexedDB()) packStore.clear().catch(() => {})
}

/** This device uses field mode: keep its pack fresh from now on. */
export function markFieldModeUsed() {
  try {
    localStorage.setItem(FIELD_USED_KEY, '1')
  } catch {
    // not remembered: the pack still syncs whenever a Field screen is open
  }
  // Ask the browser not to evict what is kept here when the device runs low
  // on space. It may say no (it decides on its own evidence, and never asks
  // the person); the answer changes nothing this code does.
  navigator.storage?.persist?.().catch(() => {})
}

function wantsPack() {
  // A phone always carries one -- it has to be on the device *before* the
  // signal goes. A desktop only does once someone has opened field mode on
  // it; a manager's browser has no reason to hold the customer list.
  if (isMobileView.value) return true
  try {
    return localStorage.getItem(FIELD_USED_KEY) === '1'
  } catch {
    return false
  }
}

let started = false

/** Keep the pack fresh in the background. Idempotent; main.js calls it once. */
export function startFieldSync() {
  if (started || !getSessionUser()) return
  started = true
  const refresh = () => {
    dropExpiredPack()
    if (wantsPack() && due()) syncPack()
  }
  loadPack().then(refresh)
  onOnline(refresh)
  document.addEventListener('visibilitychange', refresh)
  setInterval(refresh, REFRESH_MS)
}
