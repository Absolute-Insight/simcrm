// main.js imports this first, so it runs before any module creates a cached
// resource that replays IndexedDB into the page: a store another user left
// behind is cleared before anything reads it. See utils/offlineCache.js.
import { claimOfflineCache } from '@/utils/offlineCache'
import { currentUserCookie } from '@/utils/sessionExpiry'

const user = currentUserCookie(document.cookie)

/* The cached shell with no user_id cookie is not a logged-out page. The cookie
   is a session cookie and a phone drops it on closing the app; the shell's
   loader has already matched this device's offline owner against the saved
   boot (offline/bootSnapshot.js). Claiming for "nobody" here would empty the
   stores at the exact moment they exist for -- a rep opening the app at a site
   with no signal. The server settles who is logged in as soon as it answers
   (offline/connectivity.js sends a refused handshake to the login page, which
   clears everything). A cookie that says Guest is still honoured. */
const offlineStart =
  !user && !!window.__crm_offline_shell && !!window.__crm_offline_user

if (!offlineStart) {
  claimOfflineCache(user && user !== 'Guest' ? user : null)
}
