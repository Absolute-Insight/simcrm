<template>
  <Transition name="panel-slide">
    <div
      v-if="assistantVisible"
      ref="target"
      class="v-panel absolute z-20 h-screen"
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

        <AgentChat
          :messages="assistantMessages"
          :asking="assistantAsking"
          :failure="assistantFailure"
          :examples="exampleQuestions"
          :intro="intro"
          :placeholder="__('Ask about our products…')"
          :focus-when="assistantVisible"
          @send="askAssistant"
          @retry="retryLastQuestion"
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
              v-else-if="failure === 'unavailable'"
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
</template>

<script setup>
import AgentChat from '@/components/AgentChat.vue'
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
import { openHelpCenter } from '@/stores/help'
import { usersStore } from '@/stores/users'
import { activeSettingsPage, showSettings } from '@/composables/settings'
import { onClickOutside } from '@vueuse/core'
import { Badge } from 'frappe-ui'
import { ref } from 'vue'

const { isAdmin } = usersStore()

const target = ref(null)

const intro = __(
  'Ask about our products, models, materials, standards and which industries use what. Answers come only from the knowledge base your administrator maintains — nothing here reads your deals or email.',
)

const exampleQuestions = [
  __('Which valve do we recommend for a mine slurry line?'),
  __('What pressure classes do our gate valves come in?'),
  __('Which standards do our valves comply with?'),
]

function failureCopy(failure) {
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
