<template>
  <Transition name="panel-slide">
    <div
      v-if="suggestionsVisible"
      ref="target"
      class="absolute z-20 h-screen bg-surface-base"
      :style="{
        'box-shadow': 'var(--elevation-lg)',
        'max-width': 'min(400px, 100vw)',
        'min-width': 'min(400px, 100vw)',
        left: 'calc(100% + 1px)',
      }"
    >
      <div class="flex h-screen flex-col text-ink-gray-9">
        <div class="flex items-center justify-between">
          <div class="v-title-sm text-ink-gray-8 px-4 pt-[15px] pb-3">
            {{ __('Suggestions') }}
          </div>
          <Button
            class="mr-3"
            :tooltip="__('Refresh')"
            :aria-label="__('Refresh')"
            icon="lucide-refresh-cw"
            variant="ghost"
            :loading="suggestions.loading"
            @click="reload()"
          />
        </div>

        <!-- Closing on navigate is the panel's business, not the list's: the
             mobile page is already where the row would take you. -->
        <SuggestionsList :on-navigate="toggle" />
      </div>
    </div>
  </Transition>
</template>
<script setup>
import SuggestionsList from '@/components/SuggestionsList.vue'
import {
  suggestionsVisible,
  suggestions,
  suggestionsStore,
} from '@/stores/suggestions'
import { globalStore } from '@/stores/global'
import { onClickOutside } from '@vueuse/core'
import { onBeforeUnmount, onMounted, ref } from 'vue'

const { toggle, reload } = suggestionsStore()
const { $socket } = globalStore()

const target = ref(null)

/* The signal engine publishes one event per affected user per run
   (crm.agent.signals.publish_new_suggestions), so the inbox refreshes itself
   instead of being right only when clicked. The handler is passed to `off` by
   reference because RecordSuggestions listens to the same event — a bare
   `off('crm_suggestion')` would unsubscribe both.

   It lives on this shell rather than inside SuggestionsList because the shell
   is mounted for the whole session while the list only exists while the panel
   is open. `reload()` refreshes openCount, which is the sidebar badge — moving
   this into the list would leave the badge stale until somebody opened the
   panel, which is the one moment it no longer needs to be right. */
function onSuggestionEvent() {
  reload()
}

onMounted(() => $socket.on('crm_suggestion', onSuggestionEvent))
onBeforeUnmount(() => $socket.off('crm_suggestion', onSuggestionEvent))

onClickOutside(
  target,
  () => {
    if (suggestionsVisible.value) toggle()
  },
  {
    ignore: ['#suggestions-btn', '.field-layout-dialog', '[role="dialog"]'],
  },
)
</script>

<style scoped>
/* The panel used to carry `transition-all` on a v-if element, which animates
   nothing — an element that does not exist has no property to transition from.
   A real transition needs the element wrapped. */
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
