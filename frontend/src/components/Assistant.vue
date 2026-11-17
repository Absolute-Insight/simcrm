<template>
  <Transition name="panel-slide">
    <div
      v-if="assistantVisible"
      ref="target"
      class="v-panel"
      :class="
        mobile
          ? 'fixed inset-0 z-30 h-dvh w-screen !border-r-0 pb-[env(safe-area-inset-bottom)]'
          : 'absolute z-20 h-screen'
      "
      :style="
        mobile
          ? {}
          : {
              'box-shadow': 'var(--elevation-lg)',
              'max-width': 'min(420px, 100vw)',
              'min-width': 'min(420px, 100vw)',
              left: 'calc(100% + 1px)',
            }
      "
      :role="mobile ? 'dialog' : undefined"
      :aria-modal="mobile ? 'true' : undefined"
      :aria-label="mobile ? __('Assistant') : undefined"
    >
      <div
        class="flex flex-col text-ink-gray-9"
        :class="mobile ? 'h-full' : 'h-screen'"
      >
        <div class="flex items-center justify-between">
          <div class="v-title-sm px-4 pb-3 pt-[15px] text-ink-gray-8">
            {{ __('Assistant') }}
          </div>
          <div class="mr-3 flex items-center gap-1">
            <Button
              v-if="assistantMessages.length"
              :tooltip="__('Clear the conversation')"
              :aria-label="__('Clear the conversation')"
              icon="lucide-eraser"
              variant="ghost"
              @click="clearAssistant"
            />
            <!-- Full screen has no "outside" to tap, so it closes by name. -->
            <Button
              v-if="mobile"
              :aria-label="__('Close the assistant')"
              icon="lucide-x"
              variant="ghost"
              @click="toggleAssistant"
            />
          </div>
        </div>

        <AgentChat
          :messages="assistantMessages"
          :asking="assistantAsking"
          :failure="assistantFailure"
          :failure-reason="assistantFailureReason"
          :examples="exampleQuestions"
          :intro="intro"
          :placeholder="__('Ask about our products…')"
          :focus-when="assistantVisible"
          :can-attach="!!assistantCapabilities?.attachments"
          :accept="(assistantCapabilities?.accept || []).join(',')"
          :attachment="assistantAttachment"
          :attach-file="attachToAssistant"
          :can-dictate="!!assistantCapabilities?.dictation"
          :max-clip-seconds="assistantCapabilities?.max_clip_seconds || 30"
          @send="askAssistant"
          @retry="retryLastQuestion"
          @detach="detachFromAssistant"
        >
          <template #message-extra="{ message }">
            <!-- Sources are the knowledge articles the server actually
                 loaded, by title: a rep on a call wants to know where the
                 answer came from, not a link to an admin page. -->
            <div v-if="message.sources?.length" class="flex flex-wrap gap-1.5">
              <Badge
                v-for="source in message.sources"
                :key="source.name"
                variant="subtle"
                :label="source.title"
              />
            </div>
            <!-- Reference rows: every figure in the answer is on one of
                 these. Each opens the row on its page so the rep can check. -->
            <div
              v-if="message.references?.length"
              class="flex flex-col gap-1.5"
            >
              <button
                v-for="row in message.references"
                :key="row.name"
                type="button"
                class="flex w-full items-start gap-2 rounded-6 border border-outline-gray-2 px-2.5 py-1.5 text-left hover:bg-surface-gray-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
                @click="openReference(row)"
              >
                <PhFileText
                  class="mt-0.5 size-4 shrink-0 text-ink-gray-5"
                  aria-hidden="true"
                />
                <span class="flex min-w-0 flex-col">
                  <span class="text-sm text-ink-gray-8">{{ row.label }}</span>
                  <span class="text-xs text-ink-gray-5">
                    {{ row.sheet_title }} ·
                    {{ __('page {0}', [row.page]) }}
                  </span>
                </span>
              </button>
              <p class="text-xs text-ink-gray-5">
                {{
                  message.fromSheet
                    ? __(
                        'Taken straight from the sheet. Tap a row to see it on the page.',
                      )
                    : __(
                        'Every figure above is on these rows. Tap one to see it on the page.',
                      )
                }}
              </p>
            </div>
          </template>

          <template #failure="{ failure }">
            <p class="text-sm text-ink-gray-6">
              {{ failureCopy(failure) }}
            </p>
          </template>

          <template #failure-actions="{ failure }">
            <template v-if="failure === 'disabled'">
              <Button
                v-if="isAdmin()"
                size="sm"
                variant="subtle"
                :label="__('Open assistant settings')"
                @click="openSettingsPage('Assistant')"
              />
              <Button
                size="sm"
                variant="outline"
                :label="__('Open the help center')"
                @click="openHelpCenter()"
              />
            </template>
            <Button
              v-else-if="failure === 'empty' && isAdmin()"
              size="sm"
              variant="subtle"
              :label="__('Open Settings → Knowledge')"
              @click="openSettingsPage('Knowledge')"
            />
            <Button
              v-else-if="
                failure === 'unavailable' &&
                canRetryUnavailable(assistantFailureReason)
              "
              size="sm"
              variant="subtle"
              :label="__('Try again')"
              @click="retryLastQuestion"
            />
          </template>
        </AgentChat>
      </div>
    </div>
  </Transition>
  <ReferenceViewerModal v-model="referenceOpen" :reference="openRow" />
</template>

<script setup>
import AgentChat from '@/components/AgentChat.vue'
import ReferenceViewerModal from '@/components/Modals/ReferenceViewerModal.vue'
import { PhFileText } from '@phosphor-icons/vue'
import {
  askAssistant,
  assistantAttachment,
  assistantCapabilities,
  attachToAssistant,
  detachFromAssistant,
  loadAssistantCapabilities,
  assistantAsking,
  assistantFailure,
  assistantFailureReason,
  assistantMessages,
  assistantVisible,
  clearAssistant,
  retryLastQuestion,
  toggleAssistant,
} from '@/stores/assistant'
import { openHelpCenter } from '@/stores/help'
import {
  unavailableReasonMessage,
  canRetryUnavailable,
} from '@/utils/agentStatus'
import { usersStore } from '@/stores/users'
import { activeSettingsPage, showSettings } from '@/composables/settings'
import { onClickOutside, useEventListener } from '@vueuse/core'
import { Badge } from 'frappe-ui'
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'

const { isAdmin } = usersStore()

const props = defineProps({
  // a phone: over the whole screen, closed by its own button
  mobile: { type: Boolean, default: false },
})

watch(
  assistantVisible,
  (open) => {
    if (open) loadAssistantCapabilities()
  },
  { immediate: true },
)

const target = ref(null)

/* On a phone the panel opens from the menu drawer, and the drawer hands focus
   back to its own button as it closes -- after the chat has focused its box.
   So the box is focused again once the drawer has gone, and Escape is heard on
   the window rather than on a panel that may not hold the focus. */
const DRAWER_LEAVE_MS = 250
watch(assistantVisible, (open) => {
  if (!open || !props.mobile) return
  setTimeout(() => {
    if (assistantVisible.value) target.value?.querySelector('textarea')?.focus()
  }, DRAWER_LEAVE_MS)
})
useEventListener(window, 'keydown', (event) => {
  if (event.key !== 'Escape' || !props.mobile || !assistantVisible.value) return
  // a dialog open above the panel (a reference sheet, Settings, the help
  // center, the command palette) takes this Escape; the panel takes the next
  if (referenceOpen.value) return
  if (document.querySelector('[role="dialog"][data-state="open"]')) return
  toggleAssistant()
})

/* Over the whole screen, the page underneath is out of sight: going back, or
   following a link in an answer, must not leave the panel covering the page
   the rep has just moved to. */
const route = useRoute()
watch(
  () => route.fullPath,
  () => {
    if (props.mobile && assistantVisible.value) toggleAssistant()
  },
)

const referenceOpen = ref(false)
const openRow = ref(null)

function openReference(row) {
  openRow.value = row
  referenceOpen.value = true
}

const intro = __(
  'Ask about our products, models, materials, standards and which industries use what. Answers come only from the knowledge base your administrator maintains — nothing here reads your deals or email.',
)

const exampleQuestions = [
  __('Which valve do we recommend for a mine slurry line?'),
  __('What pressure classes do our gate valves come in?'),
  __('Which ISO certifications does the company hold?'),
]

function failureCopy(failure) {
  if (failure === 'rejected' && assistantFailureReason.value) {
    // the server's own sentence about what it could not read
    return assistantFailureReason.value
  }
  if (
    failure === 'unavailable' &&
    unavailableReasonMessage(assistantFailureReason.value)
  ) {
    // a spent budget or a question the model had no room for is not weather
    return unavailableReasonMessage(assistantFailureReason.value)
  }
  if (failure === 'disabled') {
    return isAdmin()
      ? __(
          'The assistant is switched off. Point it at a model endpoint in Settings → Assistant to enable it.',
        )
      : __(
          'The assistant is switched off for this site. Ask your administrator to enable it — the help center works either way.',
        )
  }
  if (failure === 'empty') {
    return isAdmin()
      ? __(
          'No knowledge has been added yet. Add articles or import the sample pack in Settings → Knowledge.',
        )
      : __(
          'Your administrator has not added product knowledge yet, so there is nothing to answer from.',
        )
  }
  return __(
    'The assistant could not be reached right now. Your question was not lost — try again in a moment.',
  )
}

function openSettingsPage(page) {
  activeSettingsPage.value = page
  showSettings.value = true
}

onClickOutside(
  target,
  () => {
    // nothing is outside a panel that covers the screen
    if (assistantVisible.value && !props.mobile) toggleAssistant()
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
