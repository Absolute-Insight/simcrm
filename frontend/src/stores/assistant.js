/**
 * The sidebar Assistant panel's state: a session-local chat over
 * `crm.agent.api.ask_assistant`, which answers from the knowledge base an
 * administrator curates in Settings → Knowledge.
 *
 * One instance of the shared chat store (see `agentChat.js`). Answers are
 * rendered as plain text, never HTML, and `sources` only ever contains
 * articles the server actually loaded.
 */
import { createChatStore } from '@/stores/agentChat'
import { plainTextAnswer } from '@/utils/assistantText'

const store = createChatStore({
  method: 'crm.agent.api.ask_assistant',
  mapResult: (result) => ({
    content: plainTextAnswer(result.answer),
    sources: result.sources || [],
  }),
})

export { HISTORY_TURNS_SENT } from '@/stores/agentChat'

export const assistantVisible = store.visible

/** `{ role: 'user'|'assistant', content: string, sources?: [{name,title}] }` */
export const assistantMessages = store.messages

export const assistantAsking = store.asking
export const assistantFailure = store.failure
export const assistantFailureReason = store.failureReason

export const toggleAssistant = store.toggle
export const clearAssistant = store.clear
export const askAssistant = store.ask
export const retryLastQuestion = store.retry
