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
