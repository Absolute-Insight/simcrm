// The email bodies this tab has fetched, by Communication name, for one user.
// Kept apart from composables/useEmailBody so utils/offlineCache can clear it
// on logout and on a lost session without importing frappe-ui that early.
//
// Every read checks who is logged in now: another tab that logs out and in as
// someone else changes the `user_id` cookie this tab shares, and what the
// first user could read must not be served to the second.
const MAX_BODIES = 40

const bodies = new Map()
const pending = new Map()
let owner

// Parsed here rather than imported from utils/sessionExpiry, which imports
// utils/offlineCache, which imports this module.
function currentUser() {
  try {
    const cookies = new URLSearchParams(
      String(document.cookie ?? '')
        .split('; ')
        .join('&'),
    )
    return cookies.get('user_id') || null
  } catch {
    return null
  }
}

/** The bodies map, emptied first if it belongs to someone else. */
function own() {
  const user = currentUser()
  if (user !== owner) {
    bodies.clear()
    pending.clear()
    owner = user
  }
  return user
}

export function emailBodyOwner() {
  return own()
}

export function rememberEmailBody(name, content, forUser = own()) {
  if (!name || typeof content !== 'string') return
  // an answer to a request made for whoever was logged in before
  if (own() !== forUser) return
  bodies.delete(name)
  bodies.set(name, content)
  while (bodies.size > MAX_BODIES) bodies.delete(bodies.keys().next().value)
}

export function cachedEmailBody(name) {
  own()
  return bodies.get(name)
}

export function pendingEmailBody(name) {
  own()
  return pending.get(name)
}

export function trackPendingEmailBody(name, request) {
  pending.set(name, request)
  request
    .finally(() => {
      if (pending.get(name) === request) pending.delete(name)
    })
    .catch(() => {})
}

export function forgetEmailBodies() {
  bodies.clear()
  pending.clear()
  owner = undefined
}
