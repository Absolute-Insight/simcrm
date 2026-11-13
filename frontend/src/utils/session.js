/**
 * Who this page is for.
 *
 * The `user_id` cookie, as ever -- except in a shell the service worker served
 * from its cache, where the cookie may simply be gone: it is a session cookie,
 * and a phone drops those when it closes the app. There the user is the one
 * the shell's loader established from this device's offline stores
 * (offline/bootSnapshot.js), and the server gets the final say the moment it
 * can be reached. A Guest cookie always means logged out.
 */
export function getSessionUser() {
  const cookies = new URLSearchParams(document.cookie.split('; ').join('&'))
  const user = cookies.get('user_id')
  if (user === 'Guest') return null
  if (user) return user
  return (window.__crm_offline_shell && window.__crm_offline_user) || null
}
