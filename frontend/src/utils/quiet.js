/**
 * Await a frappe-ui resource call without letting its failure surface twice.
 *
 * A failed resource rejects *as well as* setting `.error` (frappe-ui's
 * handleError rethrows after onError), and there is no app-level
 * errorHandler. So a bare `resource.reload()` whose rejection nobody awaits
 * becomes an unhandled rejection on top of the ErrorState the page already
 * renders from `.error`. Wrap fire-and-forget reloads in this.
 *
 * Anything non-promise passes straight through, so `quiet(maybeUndefined)`
 * is safe for optional callbacks too.
 */
export function quiet(promise) {
  return Promise.resolve(promise).catch(() => {})
}
