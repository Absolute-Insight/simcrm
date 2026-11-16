<template>
  <div class="flex min-h-0 flex-1 flex-col text-ink-gray-9">
    <div
      ref="scroller"
      class="flex flex-1 flex-col gap-3 overflow-y-auto px-4 pb-3"
      :class="compact ? 'pt-1' : ''"
    >
      <!-- The empty state is the feature's own manual: what it is, what it
           is not, and a few questions that show the register it expects. -->
      <div v-if="!messages.length" class="flex flex-col gap-3 pt-1">
        <slot name="empty">
          <p class="text-p-sm text-ink-gray-6">{{ intro }}</p>
          <div class="flex flex-col items-start gap-1.5">
            <Button
              v-for="example in examples"
              :key="example"
              variant="outline"
              size="sm"
              :label="example"
              @click="send(example)"
            />
          </div>
        </slot>
      </div>

      <template v-for="(message, index) in messages" :key="index">
        <!-- Answers are model output: plain text on purpose, never v-html. -->
        <div
          v-if="message.role === 'user'"
          class="ml-8 flex flex-col items-end gap-1 self-end"
        >
          <div
            class="whitespace-pre-wrap rounded-6 bg-surface-gray-2 px-3 py-2 text-base text-ink-gray-8"
          >
            {{ message.content }}
          </div>
          <span
            v-if="message.attachmentName"
            class="flex max-w-full items-center gap-1 text-xs text-ink-gray-5"
          >
            <PhPaperclip class="size-3 shrink-0" aria-hidden="true" />
            <span class="truncate">{{ message.attachmentName }}</span>
          </span>
        </div>
        <div v-else class="flex flex-col gap-2">
          <div
            class="whitespace-pre-wrap text-base leading-relaxed text-ink-gray-8"
          >
            {{ message.content }}
          </div>
          <slot name="message-extra" :message="message" />
        </div>
      </template>

      <div
        v-if="asking"
        class="flex items-center gap-2 text-sm text-ink-gray-5"
      >
        <LucideLoaderCircle class="size-4 animate-spin" />
        {{ __('Thinking…') }}
      </div>

      <div
        v-else-if="failure"
        class="flex flex-col items-start gap-2 rounded-6 bg-surface-gray-1 p-3"
      >
        <slot name="failure" :failure="failure">
          <p class="text-sm text-ink-gray-6">
            {{ failureText(failure) }}
          </p>
        </slot>
        <div class="flex flex-wrap gap-2">
          <slot name="failure-actions" :failure="failure">
            <Button
              v-if="
                failure === 'unavailable' && canRetryUnavailable(failureReason)
              "
              size="sm"
              variant="subtle"
              :label="__('Try again')"
              @click="emit('retry')"
            />
          </slot>
        </div>
      </div>
    </div>

    <div class="flex flex-col gap-2 border-t border-outline-gray-1 p-3">
      <!-- The attached file stays for the follow-ups until it is removed. -->
      <div
        v-if="attachment"
        class="flex items-center gap-2 self-start rounded-6 border border-outline-gray-2 bg-surface-gray-1 py-1 pl-2 pr-1 text-sm text-ink-gray-7"
      >
        <component
          :is="attachment.kind === 'image' ? PhImage : PhFileText"
          class="size-4 shrink-0 text-ink-gray-5"
          aria-hidden="true"
        />
        <span class="max-w-[14rem] truncate" :title="attachment.name">
          {{ attachment.name }}
        </span>
        <span class="shrink-0 text-xs text-ink-gray-5">
          {{ fileSize(attachment.size) }}
        </span>
        <Button
          variant="ghost"
          size="sm"
          :icon="PhX"
          :aria-label="__('Remove {0}', [attachment.name])"
          :tooltip="__('Remove attachment')"
          @click="emit('detach')"
        />
      </div>

      <!-- Recording replaces the box: one thing happening at a time, and the
           clock says how much of the limit is left. -->
      <div
        v-if="dictation.state.value === 'recording'"
        class="flex min-h-9 items-center gap-3 rounded-6 bg-surface-gray-2 py-1 pl-3 pr-1"
        role="status"
        aria-live="polite"
      >
        <span
          class="size-2.5 shrink-0 animate-pulse rounded-full bg-surface-red-7"
          aria-hidden="true"
        />
        <span class="flex-1 text-base text-ink-gray-8">
          {{ __('Listening…') }}
          <span class="ml-1 tabular-nums text-ink-gray-5">
            {{ clock(dictation.elapsed.value) }} /
            {{ clock(maxClipSeconds) }}
          </span>
        </span>
        <Button
          variant="ghost"
          size="sm"
          :label="__('Cancel')"
          @click="dictation.cancel()"
        />
        <Button
          variant="solid"
          :icon="PhStop"
          :aria-label="__('Stop and transcribe')"
          :tooltip="__('Stop and transcribe')"
          @click="dictation.stop()"
        />
      </div>

      <div v-else class="flex items-end gap-1.5">
        <textarea
          ref="input"
          v-model="draft"
          rows="1"
          :placeholder="
            dictation.state.value === 'transcribing'
              ? __('Transcribing…')
              : placeholder
          "
          :disabled="dictation.state.value === 'transcribing'"
          class="max-h-32 min-h-9 flex-1 resize-none rounded-6 border-0 bg-surface-gray-2 px-3 py-2 text-base text-ink-gray-8 placeholder-ink-gray-4 focus:ring-2 focus:ring-outline-gray-3 disabled:opacity-70"
          @keydown.enter.exact.prevent="send(draft)"
          @input="autosize"
        />
        <template v-if="canAttach">
          <input
            ref="filePicker"
            type="file"
            class="hidden"
            :accept="accept"
            @change="pickFile"
          />
          <Button
            variant="ghost"
            :icon="PhPaperclip"
            :aria-label="__('Attach a file')"
            :tooltip="__('Attach a file')"
            :disabled="asking || reading"
            @click="filePicker?.click()"
          />
        </template>
        <Button
          v-if="canDictate && browserCanRecord"
          variant="ghost"
          :icon="
            dictation.state.value === 'transcribing'
              ? LucideLoaderCircle
              : PhMicrophone
          "
          :class="
            dictation.state.value === 'transcribing'
              ? '[&_svg]:animate-spin'
              : ''
          "
          :aria-label="__('Dictate')"
          :tooltip="__('Dictate (up to {0} seconds)', [maxClipSeconds])"
          :disabled="dictation.state.value === 'transcribing'"
          @click="dictation.start()"
        />
        <Button
          variant="solid"
          icon="lucide-send-horizontal"
          :aria-label="__('Send')"
          :disabled="
            !draft.trim() || asking || dictation.state.value !== 'idle'
          "
          @click="send(draft)"
        />
      </div>

      <p
        v-if="notice"
        class="text-xs text-ink-gray-6"
        role="status"
        aria-live="polite"
      >
        {{ notice }}
      </p>
    </div>
  </div>
</template>

<script setup>
/**
 * The transcript, pending indicator, degrade states and input shared by every
 * model-backed chat surface (Assistant panel, Mentor pane, Analyst page).
 * State lives in the caller's store (see stores/agentChat.js); this component
 * only renders it and emits intent.
 */
import {
  PhCircleNotch as LucideLoaderCircle,
  PhFileText,
  PhImage,
  PhMicrophone,
  PhPaperclip,
  PhStop,
  PhX,
} from '@phosphor-icons/vue'
import {
  unavailableReasonMessage,
  canRetryUnavailable,
} from '@/utils/agentStatus'
import {
  MAX_CLIP_SECONDS,
  dictationSupported,
  useDictation,
} from '@/composables/useDictation'
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  messages: { type: Array, required: true },
  asking: { type: Boolean, default: false },
  /** '' | 'disabled' | 'empty' | 'unavailable' | 'rejected' */
  failure: { type: String, default: '' },
  /** The server's reason for an unavailable status, when it gave one. */
  failureReason: { type: String, default: '' },
  examples: { type: Array, default: () => [] },
  intro: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  /** Tighter top padding for a pane that already has a header. */
  compact: { type: Boolean, default: false },
  /** Focus the input when this flips to true (a panel opening). */
  focusWhen: { type: Boolean, default: false },
  /** Offer the paperclip. The caller owns the file (see stores/assistant.js). */
  canAttach: { type: Boolean, default: false },
  /** The file input's accept list, e.g. '.pdf,.docx'. */
  accept: { type: String, default: '' },
  /** `{ name, size, kind }` of the attached file, or null. */
  attachment: { type: Object, default: null },
  /** Reads a picked file; resolves '' or the reason it was not taken. */
  attachFile: { type: Function, default: null },
  /** Offer the microphone (the site's model takes audio). */
  canDictate: { type: Boolean, default: false },
  maxClipSeconds: { type: Number, default: MAX_CLIP_SECONDS },
})

const emit = defineEmits(['send', 'retry', 'detach'])

// Fixed for the page's life: an insecure origin or an old browser has no
// recorder, and a microphone that can only apologise is clutter.
const browserCanRecord = dictationSupported()

const filePicker = ref(null)
const reading = ref(false)
const attachNotice = ref('')

const dictation = useDictation({
  onText: (text) => {
    // appended, not replacing: a rep may type half and say the rest
    draft.value = draft.value.trim() ? `${draft.value.trim()} ${text}` : text
    nextTick(() => {
      autosize()
      focus()
    })
  },
  maxSeconds: props.maxClipSeconds,
})

const dictationCopy = {
  unsupported: __('This browser cannot record audio here.'),
  denied: __(
    'Microphone access is blocked. Allow it in the browser to dictate.',
  ),
  nothing: __(
    'Nothing was heard. Try again a little closer to the microphone.',
  ),
  unavailable: __(
    'Dictation is unavailable right now. Type your question instead.',
  ),
  failed: __(
    'The recording could not be transcribed. Type your question instead.',
  ),
}

const notice = computed(() => {
  if (attachNotice.value) return attachNotice.value
  const error = dictation.error.value
  if (!error) return ''
  return dictation.errorMessage.value || dictationCopy[error] || ''
})

async function pickFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || !props.attachFile) return
  attachNotice.value = ''
  reading.value = true
  try {
    attachNotice.value = (await props.attachFile(file)) || ''
  } catch {
    attachNotice.value = __('That file could not be read.')
  } finally {
    reading.value = false
  }
}

function fileSize(bytes) {
  if (!bytes && bytes !== 0) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function clock(seconds) {
  const whole = Math.min(Math.floor(seconds), 5999)
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

const scroller = ref(null)
const input = ref(null)
const draft = ref('')

const failureCopy = {
  disabled: __(
    'This feature is switched off for this site. Ask your administrator to enable it.',
  ),
  empty: __('There is nothing to answer from yet.'),
  unavailable: __(
    'The model could not be reached right now. Your question was not lost — try again in a moment.',
  ),
}

function failureText(failure) {
  if (failure === 'rejected' && props.failureReason) return props.failureReason
  if (
    failure === 'unavailable' &&
    unavailableReasonMessage(props.failureReason)
  ) {
    // a spent budget or a question the model had no room for is not weather
    return unavailableReasonMessage(props.failureReason)
  }
  return failureCopy[failure]
}

function send(text) {
  const question = (text || '').trim()
  if (!question || props.asking) return
  draft.value = ''
  attachNotice.value = ''
  autosize()
  emit('send', question)
}

function autosize() {
  const el = input.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight}px`
}

function focus() {
  input.value?.focus()
}

defineExpose({ focus })

/* Keep the newest message on screen; also pulls the view down to the typing
   indicator while an answer is pending. */
watch(
  () => [props.messages.length, props.asking],
  async () => {
    await nextTick()
    scroller.value?.scrollTo({ top: scroller.value.scrollHeight })
  },
)

watch(
  () => props.focusWhen,
  async (open) => {
    if (open) {
      await nextTick()
      focus()
    }
  },
  { immediate: true },
)
</script>
