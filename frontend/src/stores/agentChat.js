/**
 * One chat store per model-backed surface: Mentor, Assistant, Analyst.
 *
 * Each surface is a session-local transcript over one whitelisted endpoint
 * that answers `{ status: 'ok', ... }` or a bare degrade status. The store
 * knows nothing about what an answer contains — `mapResult` turns an ok
 * result into the assistant turn's fields — so the Analyst can carry tables
 * where the Mentor carries article chips, on the same discipline:
 *
 * - The transcript lives in memory only. A manual you can re-ask beats a
 *   chat log that needs a doctype.
 * - Model output is text. Nothing here renders HTML; callers display
 *   `content` with `{{ }}`.
 * - History travels as role and content only, captured before the new
 *   question is appended: the question goes in its own parameter, and
 *   sending it twice reads to the model as the user repeating themselves.
 */
import { call } from 'frappe-ui'
import { ref } from 'vue'

import { describeError } from '@/utils/describeError'

/** How many prior turns accompany a question. The server trims again anyway. */
export const HISTORY_TURNS_SENT = 8

/**
 * @param {object} options
 * @param {string} options.method  dotted path of the whitelisted endpoint
 * @param {(result: object) => object} options.mapResult  ok result → the
 *   assistant turn's fields; must include `content`
 * @param {number} [options.historyTurns]
 * @param {() => object} [options.params]  extra arguments for each call (the
 *   Assistant's attached file); read at send time, so a retry sends what is
 *   attached now
 * @param {() => object} [options.userExtras]  extra fields on the user turn,
 *   for display only -- history still carries role and content alone
 */
export function createChatStore({
  method,
  mapResult,
  historyTurns = HISTORY_TURNS_SENT,
  params = () => ({}),
  userExtras = () => ({}),
}) {
  const visible = ref(false)

  /** `{ role: 'user'|'assistant', content: string, ...extras }` */
  const messages = ref([])

  const asking = ref(false)

  /**
   * Why the last question got no answer:
   * '' | 'disabled' | 'empty' | 'unavailable' | 'rejected'. Cleared on the
   * next attempt. 'disabled' is configuration (the tier is off), 'empty' is
   * content (the surface has nothing to answer from yet), 'unavailable' is
   * weather (endpoint down, budget spent) and worth retrying. 'rejected' is
   * the server refusing what was sent -- a file it cannot read -- and
   * `failureReason` then holds the server's own sentence, as plain text.
   */
  const failure = ref('')

  /** The server's `reason` for a degrade status, when it gave one. */
  const failureReason = ref('')

  function toggle() {
    visible.value = !visible.value
  }

  /* Bumped by clear(). Clear is live while an answer is pending, and a local
     model takes seconds: without this the late answer landed alone in the
     emptied panel and then travelled as history with the next question. An
     ask whose session has moved on drops whatever comes back. */
  let session = 0

  function clear() {
    session++
    messages.value = []
    asking.value = false
    failure.value = ''
    failureReason.value = ''
  }

  /**
   * Re-send the question that got no answer. Only meaningful when the
   * transcript ends with an unanswered user turn — the failed states render
   * the button, so the guard is belt and braces.
   */
  function retry() {
    const last = messages.value[messages.value.length - 1]
    if (!last || last.role !== 'user' || asking.value) return
    messages.value.pop()
    return ask(last.content)
  }

  async function ask(question) {
    const trimmed = (question || '').trim()
    if (!trimmed || asking.value) return

    const history = messages.value
      .slice(-historyTurns)
      .map(({ role, content }) => ({ role, content }))

    messages.value.push({ role: 'user', content: trimmed, ...userExtras() })
    asking.value = true
    failure.value = ''
    failureReason.value = ''
    const askedIn = session

    try {
      const result = await call(method, {
        question: trimmed,
        history,
        ...params(),
      })
      if (askedIn !== session) return
      if (result?.status === 'ok') {
        messages.value.push({ role: 'assistant', ...mapResult(result) })
      } else {
        failure.value =
          result?.status === 'disabled' || result?.status === 'empty'
            ? result.status
            : 'unavailable'
        failureReason.value = result?.reason || ''
      }
    } catch (error) {
      if (askedIn !== session) return
      // A refusal the server worded for a person ("That PDF is
      // password-protected.") is shown as written; anything else (network,
      // a 500) is the same story as a degraded status: no answer, try again.
      const described = describeError(error)
      const excType = String(error?.exc_type || error?.excType || '')
      if (described.message && /ValidationError/.test(excType)) {
        failure.value = 'rejected'
        failureReason.value = described.message
      } else {
        failure.value = 'unavailable'
      }
    } finally {
      if (askedIn === session) asking.value = false
    }
  }

  return {
    visible,
    messages,
    asking,
    failure,
    failureReason,
    ask,
    retry,
    clear,
    toggle,
  }
}
