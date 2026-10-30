<template>
  <div
    v-if="state"
    class="flex justify-center px-3 pb-5 sm:px-10"
    :class="{ 'pt-1': state === 'more' }"
  >
    <Button
      v-if="state === 'more'"
      variant="subtle"
      :label="__('Load older activity')"
      icon-left="lucide-history"
      @click="emit('load')"
    />
    <p v-else class="text-p-sm text-ink-gray-5">
      {{ __('Older activity is not shown here.') }}
    </p>
  </div>
</template>

<script setup>
import { Button } from 'frappe-ui'

// 'more' offers the next page of a record's history; 'capped' says the
// timeline has reached the most it will load; anything else renders nothing.
defineProps({
  state: { type: String, default: null },
})

const emit = defineEmits(['load'])
</script>
