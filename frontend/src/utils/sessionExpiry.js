/**
 * Tell an expired session apart from a genuine permission refusal.
 *
 * When frappe's session cookie lapses, every whitelisted call answers 403
 * `PermissionError` (frappe marks the body `session_expired: 1` when a stale
 * sid was presented) and the `user_id` cookie comes back as Guest. The app
 * used to render that as "You do not have access to this — ask an
 * administrator": a rep who left the tab open overnight filed a permissions
 * ticket instead of logging in again. Nothing in the SPA re-checked the
 * cookie after boot.
 */

export function currentUserCookie(cookieString) {
  const cookies = new URLSearchParams(
    String(cookieString ?? '')
      .split('; ')
      .join('&'),
  )
  return cookies.get('user_id')
}

/**
 * @param {object} error  the error frappeRequest threw (`status`, `exc_type`, `session_expired`)
 * @param {string} cookieString  document.cookie
 * @returns {boolean} true when the failure is "you are no longer logged in"
 */
export function isSessionGone(error, cookieString) {
  if (!error) return false
  if (error.session_expired) return true
  if (error.exc_type === 'AuthenticationError') return true
  const status = Number(error.status ?? error.httpStatus)
  if (status !== 401 && status !== 403) return false
  if (error.exc_type && error.exc_type !== 'PermissionError') return false
  const user = currentUserCookie(cookieString)
  return !user || user === 'Guest'
}

/** Where to send the person so they come back to the page they were on. */
export function loginUrlFor(location) {
  const here = `${location.pathname}${location.search}${location.hash}`
  return `/login?redirect-to=${encodeURIComponent(here || '/crm')}`
}
