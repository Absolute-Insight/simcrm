<template>
  <LayoutHeader>
    <template #left-header>
      <Breadcrumbs
        :items="[{ label: __('Suggestions'), route: { name: 'Suggestions' } }]"
      />
    </template>
    <template #right-header>
      <Button
        :tooltip="__('Refresh')"
        :aria-label="__('Refresh')"
        icon="lucide-refresh-cw"
        variant="ghost"
        :loading="suggestions.loading"
        @click="reload()"
      />
    </template>
  </LayoutHeader>

  <!-- A page rather than the desktop slide-over, following Notifications: a
       400px panel hung off the sidebar has nowhere to go on a phone. The list
       itself is shared, so accept/dismiss and the error handling cannot drift
       between the two. -->
  <div class="flex flex-1 flex-col overflow-hidden text-ink-gray-9">
    <SuggestionsList />
  </div>
</template>

<script setup>
import LayoutHeader from '@/components/LayoutHeader.vue'
import SuggestionsList from '@/components/SuggestionsList.vue'
import { suggestions, suggestionsStore } from '@/stores/suggestions'
import { globalStore } from '@/stores/global'
import { Breadcrumbs } from 'frappe-ui'
import { onBeforeUnmount, onMounted } from 'vue'

const { reload } = suggestionsStore()
const { $socket } = globalStore()

/* The desktop shell carries this for the whole session; on mobile this page is
   the shell, so it subscribes while it is open. Passed to `off` by reference —
   RecordSuggestions listens to the same event. */
function onSuggestionEvent() {
  reload()
}

onMounted(() => {
  // Arriving at the page is the mobile equivalent of opening the panel, which
  // reloads on toggle. Without this the list is as old as the last app load.
  reload()
  $socket.on('crm_suggestion', onSuggestionEvent)
})
onBeforeUnmount(() => $socket.off('crm_suggestion', onSuggestionEvent))
</script>
