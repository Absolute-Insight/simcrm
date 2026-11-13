/**
 * The boot values a cached shell starts from.
 *
 * Online, Frappe renders /crm with the session's boot inlined (crm/www/crm.py).
 * Offline, the service worker answers the navigation with a copy of the page
 * that has no boot in it, and this is where the values come from instead: the
 * last ones a real page load saw, kept in localStorage because the loader has
 * to run synchronously, before any module does.
 *
 * `csrf_token` is deliberately not a boot key here. A token at rest in
 * localStorage outlives the session it belongs to; the shell asks the server
 * for the live one when it gets back on the network (offline/connectivity.js).
 *
 * Nothing in this file touches a browser global at import time: vite.config.js
 * imports it to write the loader into the shell.
 */

export const BOOT_SNAPSHOT_KEY = 'crm-offline-boot'

/* The same key utils/offlineCache.js claims the offline stores under: the one
   user whose data this device holds. */
export const OFFLINE_OWNER_KEY = 'crm-offline-cache-owner'

/* get_boot() in crm/www/crm.py, minus csrf_token. A unit test reads that file
   and fails when the two drift. */
export const BOOT_KEYS = [
  'frappe_version',
  'default_route',
  'site_name',
  'socketio_port',
  'read_only_mode',
  'setup_complete',
  'sysdefaults',
  'is_demo_site',
  'demo_data_created',
  'is_fc_site',
  'translated_doctypes',
  'translated_messages',
  'timezone',
  'state_options',
]

/** `{user, saved_at, boot}` from the values a rendered page put on `source`. */
export function takeBootSnapshot(source, user, now = Date.now()) {
  const boot = {}
  for (const key of BOOT_KEYS) {
    if (source[key] !== undefined) boot[key] = source[key]
  }
  return { user, saved_at: now, boot }
}

/**
 * Remember this page load's boot for `user`. Never throws: a full or blocked
 * storage costs the next offline start, not this online one.
 * @returns {boolean} whether it was stored
 */
export function saveBootSnapshot(user, source, storage) {
  if (!user || !source?.site_name) return false
  const snapshot = takeBootSnapshot(source, user)
  try {
    storage.setItem(BOOT_SNAPSHOT_KEY, JSON.stringify(snapshot))
    return true
  } catch {
    // Over quota is the likely cause, and the translations are the bulk of
    // it. An untranslated shell beats no shell.
    try {
      delete snapshot.boot.translated_messages
      storage.setItem(BOOT_SNAPSHOT_KEY, JSON.stringify(snapshot))
      return true
    } catch {
      return false
    }
  }
}

export function clearBootSnapshot(storage) {
  try {
    storage.removeItem(BOOT_SNAPSHOT_KEY)
  } catch {
    // nothing stored, nothing to clear
  }
}

/**
 * Runs inline in the cached shell, before the app's modules.
 *
 * Who the shell is for: the `user_id` cookie when there is one, otherwise the
 * owner of this device's offline stores. `user_id` is a session cookie, and a
 * phone drops those when it closes the app -- exactly when a rep at a site
 * with no signal opens it again. An explicit Guest cookie is the server having
 * said "logged out", and is honoured.
 *
 * Self-contained on purpose (no closures, no imports): its source is written
 * into the page as text.
 */
export function loadOfflineBoot(win, cookie, storage, snapshotKey, ownerKey) {
  win.__crm_offline_shell = true
  try {
    var match = /(?:^|; )user_id=([^;]*)/.exec(cookie || '')
    var cookieUser = match ? decodeURIComponent(match[1]) : null
    if (cookieUser === 'Guest') return
    var user = cookieUser || storage.getItem(ownerKey)
    if (!user) return
    var snapshot = JSON.parse(storage.getItem(snapshotKey) || 'null')
    if (!snapshot || snapshot.user !== user || !snapshot.boot) return
    for (var key in snapshot.boot) win[key] = snapshot.boot[key]
    win.__crm_offline_user = user
  } catch {
    /* unreadable storage: the app shows its "connect once" notice */
  }
}

/** The inline `<script>` body that replaces the Jinja boot block. */
export function shellLoaderScript() {
  return (
    `;(${loadOfflineBoot.toString()})(window, document.cookie, window.localStorage, ` +
    `${JSON.stringify(BOOT_SNAPSHOT_KEY)}, ${JSON.stringify(OFFLINE_OWNER_KEY)})`
  )
}
