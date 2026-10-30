<template>
  <div
    class="flex h-9 w-full min-w-0 items-center rounded-4 px-2 text-sm"
    :class="[
      active ? 'bg-surface-gray-2' : '',
      command.disabled
        ? 'text-ink-gray-6'
        : active
          ? 'text-ink-gray-9'
          : 'text-ink-gray-7',
    ]"
  >
    <Icon
      v-if="command.icon"
      :icon="command.icon"
      class="me-2.5 size-4 shrink-0"
      :class="active ? 'text-ink-gray-9' : 'text-ink-gray-6'"
    />
    <span class="min-w-0 flex-1 truncate">
      {{ command.translate === false ? command.title : __(command.title) }}
    </span>
    <span
      v-if="command.subtitle"
      class="ms-3 max-w-[45%] shrink-0 truncate text-xs text-ink-gray-6"
    >
      {{ command.subtitle }}
    </span>
    <span
      v-if="command.badge"
      class="ms-2 shrink-0 rounded-4 bg-surface-gray-2 px-1.5 py-0.5 text-xs"
      :class="command.badgeClass || 'text-ink-gray-7'"
    >
      {{ command.badge }}
    </span>
  </div>
</template>

<script setup>
import Icon from '@/components/Icon.vue'

defineProps({
  command: { type: Object, required: true },
  active: { type: Boolean, required: true },
})
</script>
