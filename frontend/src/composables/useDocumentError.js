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
        : __('Error occurred'),
    // A PermissionError's own message says the record is out of reach, which
    // is more use than the generic sentence; the fallback is for the errors
    // that arrive with nothing to say.
    message: __(err.messages?.[0] || 'An error occurred'),
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
