<template>
  <div
    role="status"
    class="mx-3 mb-2 flex sm:mx-5 flex-wrap items-center justify-between gap-x-3 gap-y-1.5 rounded-lg border border-outline-gray-2 bg-surface-gray-1 px-3 py-2"
  >
    <p class="min-w-0 flex-1 basis-56 text-p-sm text-ink-gray-8">
      {{ message }}
    </p>
    <Button :label="actionLabel" @click="$emit('clear')" />
  </div>
</template>

<script setup>
// A list a dashboard tile opened can show what the page normally hides. Saying
// so, with the way back beside it, is what makes that state safe to leave up.
import { Button } from 'frappe-ui'

defineProps({
  message: { type: String, required: true },
  actionLabel: { type: String, required: true },
})
defineEmits(['clear'])
</script>
