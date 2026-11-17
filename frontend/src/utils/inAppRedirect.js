/**
 * The in-app path a `?redirect=` query may send someone to, or `/`.
 *
 * Only a path inside the app is followed -- not `//host`, not a scheme, not
 * the Load Failed page itself (which would loop) -- so the query cannot send
 * the person elsewhere.
 *
 * @param {unknown} target the raw query value
 * @returns {string} a path relative to the router base (`/crm`)
 */
export function inAppRedirectPath(target) {
  if (typeof target !== 'string') return '/'
  if (!target.startsWith('/') || target.startsWith('//')) return '/'
  if (target.includes('\\')) return '/'
  if (/^\/load-failed(?:[/?#]|$)/.test(target)) return '/'
  return target
}
