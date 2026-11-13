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

/* A cookie crm/www/crm.py sets on every page it renders and logout deletes:
   who this device is signed in as, kept for as long as a pack is. */
export const FIELD_USER_COOKIE = 'crm_field_user'

/**
 * Runs inline in the cached shell, before the app's modules.
 *
 * Who the shell is for. The `user_id` cookie when there is one; an explicit
 * Guest there is the server having said "logged out", and is honoured. But
 * `user_id` is a session cookie, and a phone drops those when it closes the
 * app -- exactly when a rep at a site with no signal opens it again. So the
 * server also sets a persistent cookie naming the signed-in user, and deletes
 * it on logout, from the desk as much as from here. With no `user_id`, the
 * shell is for that user, provided this device's offline stores are theirs.
 * Neither cookie proves anything to the server; they only decide whose saved
 * copy to show until the server can be asked (offline/connectivity.js).
 *
 * Only the listed boot keys are restored: what is in localStorage is not
 * allowed to name the globals it lands on.
 *
 * Self-contained on purpose (no closures, no imports): its source is written
 * into the page as text.
 */
export function loadOfflineBoot(
  win,
  cookie,
  storage,
  snapshotKey,
  ownerKey,
  fieldCookie,
  bootKeys,
) {
  win.__crm_offline_shell = true
  try {
    var read = function (name) {
      var match = new RegExp('(?:^|; )' + name + '=([^;]*)').exec(cookie || '')
      return match ? decodeURIComponent(match[1]) : null
    }
    var user = read('user_id')
    if (user === 'Guest') return
    if (!user) {
      user = read(fieldCookie)
      if (!user || storage.getItem(ownerKey) !== user) return
    }
    var snapshot = JSON.parse(storage.getItem(snapshotKey) || 'null')
    if (!snapshot || snapshot.user !== user || !snapshot.boot) return
    for (var i = 0; i < bootKeys.length; i++) {
      var key = bootKeys[i]
      if (Object.prototype.hasOwnProperty.call(snapshot.boot, key)) {
        win[key] = snapshot.boot[key]
      }
    }
    win.__crm_offline_user = user
  } catch {
    /* unreadable storage: the app shows its "connect once" notice */
  }
}

/** The inline `<script>` body that replaces the Jinja boot block. */
export function shellLoaderScript() {
  const args = [
    BOOT_SNAPSHOT_KEY,
    OFFLINE_OWNER_KEY,
    FIELD_USER_COOKIE,
    BOOT_KEYS,
  ].map((value) => JSON.stringify(value))
  return (
    `;(${loadOfflineBoot.toString()})(window, document.cookie, ` +
    `window.localStorage, ${args.join(', ')})`
  )
}
