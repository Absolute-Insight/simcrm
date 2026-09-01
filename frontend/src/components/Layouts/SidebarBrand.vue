<template>
  <!-- The sidebar header: brand, the two panel toggles, and the collapse
       control that used to live as a labelled row at the very bottom.

       One DOM order, two layouts. Collapsed, the row becomes a centred column
       -- logo, then each action on its own line -- rather than rendering the
       actions a second time somewhere else. Rendering twice would have been
       the obvious way to do it and duplicates every `id` the slot content
       carries -- and those ids are load-bearing: Notifications.vue,
       Suggestions.vue and Assistant.vue each list their toggle's id in an
       outside-click `ignore`, so a duplicate would let a click on one copy
       close the panel the other just opened. An icon the user cannot reach is
       a sidebar they cannot reopen, so nothing here is hidden when narrow. -->
  <div
    class="flex rounded-[var(--v-radius-control)] duration-300 ease-in-out"
    :class="
      isCollapsed
        ? 'flex-col items-center gap-1 px-0 py-2'
        : 'h-12 flex-row items-center px-2 py-2'
    "
  >
    <BrandLogo v-model="brand" class="h-8 max-w-16 shrink-0" />
    <!-- `flex-1` is applied only when expanded. Left on unconditionally it
         still grows at width 0 -- `flex: 1 1 0%` claims free space whatever
         the content -- which pushes the logo off centre in the collapsed
         column. Same bug the avatar had in SidebarUser. -->
    <div
      class="flex flex-col truncate text-left duration-300 ease-in-out"
      :class="
        isCollapsed
          ? 'ml-0 w-0 flex-none overflow-hidden opacity-0'
          : 'ml-2 w-auto flex-1 opacity-100'
      "
    >
      <div
        class="truncate font-display text-base font-extrabold leading-none tracking-tight text-ink-gray-9"
      >
        {{ __(brand.name || 'Vectora') }}
      </div>
    </div>

    <!-- Notifications and Suggestions live here as icons rather than as
         labelled rows in the nav below: they open slide-overs, they are not
         places in the app, and the nav list is now ordered by what a rep
         actually works through. -->
    <div
      class="flex shrink-0 items-center"
      :class="isCollapsed ? 'flex-col gap-1' : 'flex-row gap-1'"
    >
      <slot name="actions" />
      <button
        class="grid size-6 shrink-0 place-items-center rounded-[var(--v-radius-control)] text-ink-gray-7 hover:bg-surface-gray-2"
        :aria-label="
          isCollapsed ? __('Expand sidebar') : __('Collapse sidebar')
        "
        :title="isCollapsed ? __('Expand sidebar') : __('Collapse sidebar')"
        @click="emit('toggle')"
      >
        <CollapseSidebar
          class="size-4 duration-300 ease-in-out"
          :class="isCollapsed && '[transform:rotateY(180deg)]'"
        />
      </button>
    </div>
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
