// main.js imports this first, so it runs before any module creates a cached
// resource that replays IndexedDB into the page: a store another user left
// behind is cleared before anything reads it. See utils/offlineCache.js.
import { claimOfflineCache } from '@/utils/offlineCache'
import { currentUserCookie } from '@/utils/sessionExpiry'

const user = currentUserCookie(document.cookie)
claimOfflineCache(user && user !== 'Guest' ? user : null)
