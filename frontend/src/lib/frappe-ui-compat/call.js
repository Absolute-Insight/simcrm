import { call as frappeCall } from 'frappe-ui-actual'
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
 */
export default function call(method, args, options) {
  return frappeCall(method, args, options).catch((error) => {
    redirectIfSessionGone(error)
    throw error
  })
}
