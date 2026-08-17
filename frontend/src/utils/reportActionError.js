import { toast } from 'frappe-ui'
import { describeError } from '@/utils/describeError'

/**
 * The sentence to show when an *action* fails.
 *
 * `ErrorState` covers a surface that could not load. This covers the other
 * half: a thing the rep asked for that did not happen. Those are inherited
 * `call(...).then(...)` sites with no rejection handler — assign, unassign,
 * bulk edit, rename, save a view. On failure the `.then` simply never ran, so
 * the modal stayed open or the list never reloaded and nothing said why. A rep
 * reads that as the app ignoring them.
 *
 * Pure and separate from the toast so it can be unit-tested against the real
 * error shapes; `reportActionError` in the component does the surfacing.
 *
 * The kinds mirror ErrorState's copy deliberately — the same failure must not
 * be described two different ways depending on which half of the app it
 * happened in — but the sentences are shorter, because a toast is glanced at.
 *
 * @param {unknown} error Anything a rejected `call()` produced.
 * @param {string} [fallback] What the caller was trying to do, e.g.
 *   "Could not assign." Used when the server wrote no human sentence.
 * @returns {string} A sentence to show. Never empty.
 */
export function actionErrorMessage(error, fallback = '') {
  const { kind, message } = describeError(error)

  /* The server's own sentence wins whenever it wrote one for a person:
     "Cannot delete, this Deal is linked to a Quotation" beats any generic
     copy this function could pick. describeError only promotes text that was
     meant for a human. */
  if (message) return message

  /* None of these promise that nothing was written. A dropped connection can
     still have reached the server, and a 500 can arrive after the change was
     made — so the copy says what to do next, and never "nothing was changed",
     which would be a reassurance this layer cannot honestly give. */
  switch (kind) {
    case 'offline':
      return __('Cannot reach the server. Check your connection and try again.')
    case 'permission':
      return __('You do not have permission to do that.')
    case 'notfound':
      return __('That record is not here any more.')
    default:
      return fallback || __('Something went wrong. Try again.')
  }
}

/**
 * Surface a failed action to the person who triggered it.
 *
 * Attach to any `call(...)` whose `.then` does the visible work — closing a
 * modal, reloading a list. Those bodies already only run on success; the whole
 * bug is that failure ran nothing at all.
 *
 * @param {unknown} error Anything a rejected `call()` produced.
 * @param {string} [fallback] What the caller was trying to do.
 */
export function reportActionError(error, fallback = '') {
  const message = actionErrorMessage(error, fallback)
  toast.error(message)
  // The sentence is for the rep; the stack is for whoever they report it to.
  console.error(error)
  return message
}
