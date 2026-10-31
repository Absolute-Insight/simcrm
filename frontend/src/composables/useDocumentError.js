/**
 * The full-page failure state for a record that could not be loaded.
 *
 * `useDocument` toasts on a load failure and leaves the page to decide what to
 * put on screen. Deal and Lead each wrote the same watcher inline; Organization
 * and Contact declared `errorTitle`/`errorMessage`, rendered an ErrorPage
 * branch on them -- and never assigned them, so the branch was dead and a
 * missing or forbidden record showed an empty screen with no header and no way
 * back. The mobile variants of both had no branch at all.
 *
 * One copy, so a page cannot half-implement it again.
 */
import { ref, watch } from 'vue'

/* Frappe's wording for a record a has_permission hook refused. It names the
   mechanism, not the situation, and a rep following a link to a colleague's
   customer or deal is the everyday way to reach it. */
const FRAMEWORK_REFUSAL = 'Not allowed via controller permission check'

/**
 * The sentence to show for a load failure's first server message.
 *
 * @param {string} [message]
 */
export function readableLoadError(message) {
  if (message === FRAMEWORK_REFUSAL) {
    return __(
      'You do not have access to this record. Ask a manager if it should be assigned to you.',
    )
  }
  return __(message || 'An error occurred')
}

/**
 * Title and message for a document load error. Pure, so it can be tested.
 *
 * @param {object|string|null} err The error `useDocument` reported.
 */
export function documentErrorCopy(err) {
  if (!err) return { title: '', message: '' }
  return {
    title:
      err.exc_type === 'DoesNotExistError'
        ? __('Document not found')
        : err.messages?.[0] === FRAMEWORK_REFUSAL
          ? __('No access')
          : __('Error occurred'),
    // A PermissionError's own message says the record is out of reach, which
    // is more use than the generic sentence; the fallback is for the errors
    // that arrive with nothing to say.
    message: readableLoadError(err.messages?.[0]),
  }
}

/**
 * @param {import('vue').Ref} error The `error` ref from `useDocument`.
 */
export function useDocumentError(error) {
  const errorTitle = ref('')
  const errorMessage = ref('')

  watch(
    error,
    (err) => {
      const { title, message } = documentErrorCopy(err)
      errorTitle.value = title
      errorMessage.value = message
    },
    { immediate: true },
  )

  return { errorTitle, errorMessage }
}
