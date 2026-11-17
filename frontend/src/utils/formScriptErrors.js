/**
 * What to show a Form Script author when their `onValidate` blocks a save.
 *
 * The guide states the contract plainly: "Throw a `new Error` (or call
 * `throwError`) to block the save — the error message is shown as a toast
 * automatically." Only `throwError` ever did that, because it toasts before it
 * throws. A plain `new Error` — the idiom the sentence lists *first* — aborted
 * the save in complete silence, which reads to the rep as a save button that
 * does nothing.
 *
 * Pure so it can be tested; `data/document.js` does the surfacing.
 *
 * @param {unknown} error Whatever the script threw.
 * @param {string} fallback Sentence to use when the throw carried no message.
 * @returns {string|null} The sentence to toast, or `null` when the error has
 *   already been reported and toasting again would say it twice.
 */
export function validationErrorMessage(error, fallback) {
  // `throwError` toasts on the way out, and it is also called from field hooks
  // where nothing else would report. Marking its error is what lets both paths
  // stay correct without either double-reporting.
  if (error?.__reported) return null

  const message = typeof error === 'string' ? error : error?.message
  return String(message || '').trim() || fallback
}

/**
 * Tell the caller of a save that it was blocked before it was sent.
 *
 * `useDocument` wraps `save.submit` so a failing `onValidate` or a missing
 * mandatory field stops the request. Returning early skipped the caller's
 * per-submit `onError`, and that is where `updateField` puts the edited value
 * back -- so a value that was never saved stayed on screen as if it had been.
 * A blocked save now reaches the same handler a failed one does.
 *
 * Only the per-submit handler is called: the resource-level `onError` reports
 * a server failure and runs the script's own onError, and the block has
 * already been reported by whatever blocked it.
 *
 * @param {Array} submitArgs The arguments `save.submit` was called with,
 *   `(params, options)`.
 * @param {string} message Why the save did not go through.
 * @returns {Error} The error handed to `onError`, with the `messages` shape a
 *   server error has, so a handler that shows `err.messages[0]` still works.
 */
export function rejectBlockedSave(submitArgs, message) {
  const error = new Error(message)
  error.messages = message ? [message] : []
  error.blocked = true
  submitArgs?.[1]?.onError?.(error)
  return error
}
