/**
 * The sidebar Assistant panel's state: a session-local chat over
 * `crm.agent.api.ask_assistant`, which answers from the knowledge base an
 * administrator curates in Settings → Knowledge.
 *
 * One instance of the shared chat store (see `agentChat.js`). Answers are
 * rendered as plain text, never HTML, and `sources` only ever contains
 * articles the server actually loaded.
 *
 * A rep may attach one file -- a customer's RFQ, a datasheet, a photo of a
 * nameplate. It stays attached for the follow-ups until it is removed or the
 * conversation is cleared, and travels with every question: the server keeps
 * nothing, so the file is the client's to resend. It lives in memory only.
 */
import { createChatStore } from '@/stores/agentChat'
import { plainTextAnswer } from '@/utils/assistantText'
import { bytesToBase64 } from '@/utils/wav'
import { call } from 'frappe-ui'
import { ref } from 'vue'

/** `{ name, size, kind: 'text'|'image', data }` -- `data` is base64 */
export const assistantAttachment = ref(null)

const store = createChatStore({
  method: 'crm.agent.api.ask_assistant',
  mapResult: (result) => ({
    content: plainTextAnswer(result.answer),
    sources: result.sources || [],
    // reference-sheet rows the answer was checked against (see
    // crm/agent/reference.py); fromSheet when the answer is the rows themselves
    references: result.references || [],
    fromSheet: !!result.from_sheet,
  }),
  params: () =>
    assistantAttachment.value
      ? {
          attachment: {
            name: assistantAttachment.value.name,
            data: assistantAttachment.value.data,
          },
        }
      : {},
  userExtras: () =>
    assistantAttachment.value
      ? { attachmentName: assistantAttachment.value.name }
      : {},
})

export { HISTORY_TURNS_SENT } from '@/stores/agentChat'

export const assistantVisible = store.visible

/** `{ role: 'user'|'assistant', content: string, sources?: [{name,title}], references?: [...] }` */
export const assistantMessages = store.messages

export const assistantAsking = store.asking
export const assistantFailure = store.failure
export const assistantFailureReason = store.failureReason

export const toggleAssistant = store.toggle
export const askAssistant = store.ask
export const retryLastQuestion = store.retry

export function clearAssistant() {
  store.clear()
  assistantAttachment.value = null
}

const IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp']

/** What this site's Assistant input may offer; fetched once per session. */
export const assistantCapabilities = ref(null)
let capabilitiesRequest = null

export function loadAssistantCapabilities() {
  if (!capabilitiesRequest) {
    capabilitiesRequest = call('crm.agent.api.chat_capabilities')
      .then((caps) => (assistantCapabilities.value = caps))
      .catch(() => {
        // offline or the tier is unreachable: offer nothing, ask again later
        capabilitiesRequest = null
        assistantCapabilities.value = null
      })
  }
  return capabilitiesRequest
}

function extensionOf(name) {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot).toLowerCase() : ''
}

/**
 * Read `file` into the attachment slot. Returns '' on success, or a sentence
 * saying why the file was not taken (checked again by the server, which is
 * the one that decides).
 * @param {File} file
 */
export async function attachToAssistant(file) {
  const caps = assistantCapabilities.value
  const accept = caps?.accept || []
  const extension = extensionOf(file.name)
  if (!accept.includes(extension)) {
    return caps?.images
      ? __('Attach a PDF, Word, Excel, text, CSV or image file.')
      : __('Attach a PDF, Word (.docx), Excel (.xlsx), text or CSV file.')
  }
  const isImage = IMAGE_EXTENSIONS.includes(extension)
  const limitMb = isImage ? 5 : caps?.max_attachment_mb || 10
  if (file.size > limitMb * 1024 * 1024) {
    return __('That file is larger than {0} MB.', [limitMb])
  }
  const bytes = new Uint8Array(await file.arrayBuffer())
  assistantAttachment.value = {
    name: file.name,
    size: file.size,
    kind: isImage ? 'image' : 'text',
    data: bytesToBase64(bytes),
  }
  return ''
}

export function detachFromAssistant() {
  assistantAttachment.value = null
}
