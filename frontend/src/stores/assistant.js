/**
 * The global assistant panel's state: a session-local chat over
 * `crm.agent.api.ask_assistant`.
 *
 * The transcript lives in memory only — the assistant answers questions about
 * the product, and a manual you can re-ask beats a chat log that needs a
 * doctype. Module-level refs, the same shape the other shell panels use.
 *
 * Model output discipline: answers are rendered as plain text, never HTML,
 * and `relatedArticles` only ever contains names the server has already
 * checked against the real article catalogue.
 */
import { call } from 'frappe-ui'
import { ref } from 'vue'

export const assistantVisible = ref(false)

/** `{ role: 'user'|'assistant', content: string, relatedArticles?: string[] }` */
export const assistantMessages = ref([])

export const assistantAsking = ref(false)

/**
 * Why the last question got no answer: '' | 'disabled' | 'unavailable'.
 * Cleared on the next attempt. 'disabled' is configuration (the tier is off);
 * 'unavailable' is weather (endpoint down, budget spent) and worth retrying.
 */
export const assistantFailure = ref('')

export function toggleAssistant() {
  assistantVisible.value = !assistantVisible.value
}

export function clearAssistant() {
  assistantMessages.value = []
  assistantFailure.value = ''
}

/** How many prior turns accompany a question. The server trims again anyway. */
export const HISTORY_TURNS_SENT = 8

/**
 * Re-send the question that got no answer. Only meaningful when the
 * transcript ends with an unanswered user turn — the failed states render
 * the button, so the guard is belt and braces.
 */
export function retryLastQuestion() {
  const last = assistantMessages.value[assistantMessages.value.length - 1]
  if (!last || last.role !== 'user' || assistantAsking.value) return
  assistantMessages.value.pop()
  return askAssistant(last.content)
}

export async function askAssistant(question) {
  const trimmed = (question || '').trim()
  if (!trimmed || assistantAsking.value) return

  // History is captured before the new question is appended: the question
  // travels in its own parameter, and sending it twice reads to the model as
  // the user repeating themselves.
  const history = assistantMessages.value
    .slice(-HISTORY_TURNS_SENT)
    .map(({ role, content }) => ({ role, content }))

  assistantMessages.value.push({ role: 'user', content: trimmed })
  assistantAsking.value = true
  assistantFailure.value = ''

  try {
    const result = await call('crm.agent.api.ask_assistant', {
      question: trimmed,
      history,
    })
    if (result?.status === 'ok') {
      assistantMessages.value.push({
        role: 'assistant',
        content: result.answer,
        relatedArticles: result.related_articles || [],
      })
    } else {
      assistantFailure.value =
        result?.status === 'disabled' ? 'disabled' : 'unavailable'
    }
  } catch {
    // A thrown call (network, rate limit) is the same story as a degraded
    // status for the person reading the panel: no answer, try again.
    assistantFailure.value = 'unavailable'
  } finally {
    assistantAsking.value = false
  }
}
