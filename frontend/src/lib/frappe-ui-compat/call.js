import { call as frappeCall } from 'frappe-ui-actual'
import { throughGate } from '@/offline/connectivity'
import { redirectIfSessionGone } from '@/utils/sessionExpiry'

/**
 * frappe-ui's `call()`, sending a lapsed session to log in.
 *
 * main.js does this for the resources through `resourceFetcher`, but `call()`
 * goes straight to frappeRequest and frappe-ui gives it no hook. Sending an
 * email, posting a comment, the planner and creating a deal all use it, so an
 * overnight lapse failed them with a permission toast and no redirect, until
 * the next resource fetch happened to send the rep to /login.
 *
 * Wrapped here rather than at each of the call sites, so a new one cannot
 * forget it: every `import { call } from 'frappe-ui'` resolves to this shim.
 *
 * It goes through the connectivity gate for the same reason: offline, a call
 * fails at once as "offline" instead of hanging on a dead line, and a shell
 * that booted from the cache gets its CSRF token before the first POST.
 */
export default function call(method, args, options) {
  return throughGate(() => frappeCall(method, args, options)).catch((error) => {
    redirectIfSessionGone(error)
    throw error
  })
}
