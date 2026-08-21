<template>
  <Transition name="panel-slide">
    <div
      v-if="assistantVisible"
      ref="target"
      class="absolute z-20 h-screen bg-surface-base"
      :style="{
        'box-shadow': 'var(--elevation-lg)',
        'max-width': 'min(420px, 100vw)',
        'min-width': 'min(420px, 100vw)',
        left: 'calc(100% + 1px)',
      }"
    >
      <div class="flex h-screen flex-col text-ink-gray-9">
        <div class="flex items-center justify-between">
          <div class="v-title-sm px-4 pb-3 pt-[15px] text-ink-gray-8">
            {{ __('Assistant') }}
          </div>
          <Button
            v-if="assistantMessages.length"
            class="mr-3"
            :tooltip="__('Clear the conversation')"
            :aria-label="__('Clear the conversation')"
            icon="lucide-eraser"
            variant="ghost"
            @click="clearAssistant"
          />
        </div>

        <div
          ref="scroller"
          class="flex flex-1 flex-col gap-3 overflow-y-auto px-4 pb-3"
        >
          <!-- The empty state is the feature's own manual: what it is, what it
               is not, and three questions that show the register it expects. -->
          <div
            v-if="!assistantMessages.length"
            class="flex flex-col gap-3 pt-1"
          >
            <p class="text-p-sm text-ink-gray-6">
              {{
                __(
                  'Ask how Vectora works — screens, settings, and how the numbers are computed. The assistant answers from the built-in help center and cannot read or change your records.',
                )
              }}
            </p>
            <div class="flex flex-col items-start gap-1.5">
              <Button
                v-for="example in exampleQuestions"
                :key="example"
                variant="outline"
                size="sm"
                :label="example"
                @click="send(example)"
              />
            </div>
          </div>

          <template v-for="(message, index) in assistantMessages" :key="index">
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
              <div
                v-if="message.relatedArticles?.length"
                class="flex flex-wrap gap-1.5"
              >
                <Button
                  v-for="name in message.relatedArticles"
                  :key="name"
                  variant="subtle"
                  size="sm"
                  :label="articleTitle(name)"
                  :iconLeft="LucideBookOpen"
                  @click="openHelpCenter(name)"
                />
              </div>
            </div>
          </template>

          <div
            v-if="assistantAsking"
            class="flex items-center gap-2 text-sm text-ink-gray-5"
          >
            <LucideLoaderCircle class="size-4 animate-spin" />
            {{ __('Thinking…') }}
          </div>

          <div
            v-else-if="assistantFailure === 'disabled'"
            class="flex flex-col items-start gap-2 rounded-lg bg-surface-gray-1 p-3"
          >
            <p class="text-sm text-ink-gray-6">
              {{
                isAdmin()
                  ? __(
                      'The assistant is switched off. Point it at a model endpoint in Settings → Assistant to enable it.',
                    )
                  : __(
                      'The assistant is switched off for this site. Ask your administrator to enable it — the help center works either way.',
                    )
              }}
            </p>
            <div class="flex gap-2">
              <Button
                v-if="isAdmin()"
                size="sm"
                variant="subtle"
                :label="__('Open assistant settings')"
                @click="openAssistantSettings"
              />
              <Button
                size="sm"
                variant="outline"
                :label="__('Open the help center')"
                @click="openHelpCenter()"
              />
            </div>
          </div>

          <div
            v-else-if="assistantFailure === 'unavailable'"
            class="flex flex-col items-start gap-2 rounded-lg bg-surface-gray-1 p-3"
          >
            <p class="text-sm text-ink-gray-6">
              {{
                __(
                  'The assistant could not be reached right now. Your question was not lost — try again in a moment.',
                )
              }}
            </p>
            <Button
              size="sm"
              variant="subtle"
              :label="__('Try again')"
              @click="retryLastQuestion"
            />
          </div>
        </div>

        <div class="border-t border-outline-gray-1 p-3">
          <div class="flex items-end gap-2">
            <textarea
              ref="input"
              v-model="draft"
              rows="1"
              :placeholder="__('Ask about Vectora…')"
              class="max-h-32 min-h-9 flex-1 resize-none rounded-lg border-0 bg-surface-gray-2 px-3 py-2 text-base text-ink-gray-8 placeholder-ink-gray-4 focus:ring-2 focus:ring-outline-gray-3"
              @keydown.enter.exact.prevent="send(draft)"
              @input="autosize"
            />
            <Button
              variant="solid"
              icon="lucide-send-horizontal"
              :aria-label="__('Send')"
              :disabled="!draft.trim() || assistantAsking"
              @click="send(draft)"
            />
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import LucideBookOpen from '~icons/lucide/book-open'
import LucideLoaderCircle from '~icons/lucide/loader-circle'
import {
  askAssistant,
  assistantAsking,
  assistantFailure,
  assistantMessages,
  assistantVisible,
  clearAssistant,
  retryLastQuestion,
  toggleAssistant,
} from '@/stores/assistant'
import { helpContent, openHelpCenter } from '@/stores/help'
import { usersStore } from '@/stores/users'
import { activeSettingsPage, showSettings } from '@/composables/settings'
import { onClickOutside } from '@vueuse/core'
import { computed, nextTick, ref, watch } from 'vue'

const { isAdmin } = usersStore()

const target = ref(null)
const scroller = ref(null)
const input = ref(null)
const draft = ref('')

const exampleQuestions = [
  __('What makes a deal show up as needing attention?'),
  __('How is quota attainment measured?'),
  __('How does the planner decide an item is done?'),
]

/* Chip labels come from the help catalogue when it is loaded; before that the
   article name itself, de-kebabed, is honest enough for a button. */
const articleTitles = computed(() => {
  const titles = {}
  for (const article of helpContent.data?.articles || []) {
    titles[article.name] = article.title
  }
  return titles
})

function articleTitle(name) {
  return articleTitles.value[name] || name.replaceAll('-', ' ')
}

function send(text) {
  const question = (text || '').trim()
  if (!question) return
  draft.value = ''
  autosize()
  askAssistant(question)
}

function autosize() {
  const el = input.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight}px`
}

function openAssistantSettings() {
  activeSettingsPage.value = 'Assistant'
  showSettings.value = true
}

/* Keep the newest message on screen; also pulls the panel down to the typing
   indicator while an answer is pending. */
watch(
  () => [assistantMessages.value.length, assistantAsking.value],
  async () => {
    await nextTick()
    scroller.value?.scrollTo({ top: scroller.value.scrollHeight })
  },
)

watch(assistantVisible, async (open) => {
  if (open) {
    await nextTick()
    input.value?.focus()
  }
})

onClickOutside(
  target,
  () => {
    if (assistantVisible.value) toggleAssistant()
  },
  {
    ignore: ['#assistant-btn', '.field-layout-dialog', '[role="dialog"]'],
  },
)
</script>

<style scoped>
.panel-slide-enter-active,
.panel-slide-leave-active {
  transition:
    transform var(--motion-slow) var(--motion-ease-out),
    opacity var(--motion-slow) var(--motion-ease-out);
}

.panel-slide-enter-from,
.panel-slide-leave-to {
  transform: translateX(-8px);
  opacity: 0;
}
</style>
