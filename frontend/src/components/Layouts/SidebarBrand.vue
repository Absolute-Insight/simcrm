<template>
  <!-- The sidebar header: brand, and the collapse toggle that used to live as a
       labelled row at the very bottom. Collapsed, there is no room beside the
       logo for a second control, so the toggle drops onto its own centred row
       rather than disappearing -- an icon the user cannot reach is a sidebar
       they cannot reopen. -->
  <div class="flex flex-col gap-1">
    <div
      class="flex h-12 items-center rounded-[var(--v-radius-control)] py-2 duration-300 ease-in-out"
      :class="isCollapsed ? 'justify-center px-0' : 'px-2'"
    >
      <BrandLogo v-model="brand" class="h-8 max-w-16 shrink-0" />
      <div
        class="flex flex-1 flex-col truncate text-left duration-300 ease-in-out"
        :class="
          isCollapsed
            ? 'ml-0 w-0 overflow-hidden opacity-0'
            : 'ml-2 w-auto opacity-100'
        "
      >
        <div
          class="truncate font-display text-base font-extrabold leading-none tracking-tight text-ink-gray-9"
        >
          {{ __(brand.name || 'Vectora') }}
        </div>
      </div>
      <button
        v-if="!isCollapsed"
        class="grid size-6 shrink-0 place-items-center rounded-[var(--v-radius-control)] text-ink-gray-7 hover:bg-surface-gray-2"
        :aria-label="__('Collapse sidebar')"
        :title="__('Collapse sidebar')"
        @click="emit('toggle')"
      >
        <CollapseSidebar class="size-4 duration-300 ease-in-out" />
      </button>
    </div>
    <button
      v-if="isCollapsed"
      class="mx-auto grid size-6 place-items-center rounded-[var(--v-radius-control)] text-ink-gray-7 hover:bg-surface-gray-2"
      :aria-label="__('Expand sidebar')"
      :title="__('Expand sidebar')"
      @click="emit('toggle')"
    >
      <CollapseSidebar
        class="size-4 duration-300 ease-in-out [transform:rotateY(180deg)]"
      />
    </button>
  </div>
</template>

<script setup>
import BrandLogo from '@/components/BrandLogo.vue'
import CollapseSidebar from '@/components/Icons/CollapseSidebar.vue'
import { getSettings } from '@/stores/settings'

defineProps({
  isCollapsed: { type: Boolean, default: false },
})

const emit = defineEmits(['toggle'])

const { brand } = getSettings()
</script>
