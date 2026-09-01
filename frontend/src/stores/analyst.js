/**
 * The Analyst: a chat over `crm.agent.api.ask_analyst` for administrators.
 *
 * An answer carries the narrative (model output, rendered as text) and the
 * tables Vectora computed (code output, rendered as tables). The two are
 * kept apart on purpose: every number on screen comes from `tables`, never
 * from anything parsed out of the narrative.
 */
import { createChatStore } from '@/stores/agentChat'
import { plainTextAnswer } from '@/utils/assistantText'

const store = createChatStore({
  method: 'crm.agent.api.ask_analyst',
  mapResult: (result) => ({
    content: plainTextAnswer(result.answer),
    highlights: (result.highlights || []).map(plainTextAnswer),
    caveats: (result.caveats || []).map(plainTextAnswer),
    tables: result.tables || [],
    period: result.period || {},
    sources: result.sources || [],
    currency: result.currency || '',
  }),
})

export const analystMessages = store.messages
export const analystAsking = store.asking
export const analystFailure = store.failure
export const analystFailureReason = store.failureReason
export const askAnalyst = store.ask
export const retryAnalyst = store.retry
export const clearAnalyst = store.clear
