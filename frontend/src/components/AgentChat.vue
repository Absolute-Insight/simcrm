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
          class="ml-8 self-end whitespace-pre-wrap rounded-lg bg-surface-gray-2 px-3 py-2 text-base text-ink-gray-8"
        >
          {{ message.content }}
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
        class="flex flex-col items-start gap-2 rounded-lg bg-surface-gray-1 p-3"
      >
        <slot name="failure" :failure="failure">
          <p class="text-sm text-ink-gray-6">
            {{ failureCopy[failure] }}
          </p>
        </slot>
        <div class="flex flex-wrap gap-2">
          <slot name="failure-actions" :failure="failure">
            <Button
              v-if="failure === 'unavailable'"
              size="sm"
              variant="subtle"
              :label="__('Try again')"
              @click="emit('retry')"
            />
          </slot>
        </div>
      </div>
    </div>

    <div class="border-t border-outline-gray-1 p-3">
      <div class="flex items-end gap-2">
        <textarea
          ref="input"
          v-model="draft"
          rows="1"
          :placeholder="placeholder"
          class="max-h-32 min-h-9 flex-1 resize-none rounded-lg border-0 bg-surface-gray-2 px-3 py-2 text-base text-ink-gray-8 placeholder-ink-gray-4 focus:ring-2 focus:ring-outline-gray-3"
          @keydown.enter.exact.prevent="send(draft)"
          @input="autosize"
        />
        <Button
          variant="solid"
          icon="lucide-send-horizontal"
          :aria-label="__('Send')"
          :disabled="!draft.trim() || asking"
          @click="send(draft)"
        />
      </div>
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
import { PhCircleNotch as LucideLoaderCircle } from '@phosphor-icons/vue'
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  messages: { type: Array, required: true },
  asking: { type: Boolean, default: false },
  /** '' | 'disabled' | 'empty' | 'unavailable' */
  failure: { type: String, default: '' },
  examples: { type: Array, default: () => [] },
  intro: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  /** Tighter top padding for a pane that already has a header. */
  compact: { type: Boolean, default: false },
  /** Focus the input when this flips to true (a panel opening). */
  focusWhen: { type: Boolean, default: false },
})

const emit = defineEmits(['send', 'retry'])

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

function send(text) {
  const question = (text || '').trim()
  if (!question || props.asking) return
  draft.value = ''
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
