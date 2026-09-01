/**
 * The Mentor: a chat over `crm.agent.api.ask_mentor`, grounded on the shipped
 * help articles, living inside the help center. One instance of the shared
 * chat store (see `agentChat.js`).
 *
 * `mentorOpen` is what the help center's right pane shows — the transcript
 * or an article. Asking opens the transcript; choosing an article (from the
 * tree or a citation chip) shows the article and keeps the transcript, so a
 * reader can go back to the conversation.
 */
import { createChatStore } from '@/stores/agentChat'
import { plainTextAnswer } from '@/utils/assistantText'
import { ref } from 'vue'

const store = createChatStore({
  method: 'crm.agent.api.ask_mentor',
  mapResult: (result) => ({
    content: plainTextAnswer(result.answer),
    relatedArticles: result.related_articles || [],
  }),
})

export const mentorOpen = ref(false)

/** `{ role, content, relatedArticles?: string[] }` */
export const mentorMessages = store.messages
export const mentorAsking = store.asking
export const mentorFailure = store.failure
export const clearMentor = store.clear
export const retryMentor = store.retry

export async function askMentor(question) {
  mentorOpen.value = true
  return store.ask(question)
}
