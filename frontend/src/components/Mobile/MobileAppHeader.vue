<template>
  <div class="v-head-band flex min-h-[var(--v-toolbar-h)] pr-3">
    <div class="z-20 ml-2 flex items-center justify-center">
      <Button
        class="size-7"
        variant="ghost"
        @click="sidebarOpened = !sidebarOpened"
      >
        <MenuIcon class="h-4 text-ink-gray-9" />
      </Button>
      <Button
        class="w-7"
        variant="ghost"
        :icon="LucideSearch"
        :aria-label="__('Search')"
        @click="openCommandPalette"
      />
    </div>
    <!-- min-w-0: a flex child will not shrink below its content otherwise, and
         a long record title or a row of page actions pushed the header wider
         than the phone, taking the status menu or Save off the screen -->
    <div id="app-header" class="min-w-0 flex-1" />
  </div>
  <CallUI />
</template>

<script setup>
import MenuIcon from '@/components/Icons/MenuIcon.vue'
import CallUI from '@/components/Telephony/CallUI.vue'
import { mobileSidebarOpened as sidebarOpened } from '@/composables/settings'
import { openCommandPalette } from '@/composables/useCommandPalette'
import LucideSearch from '~icons/lucide/search'
</script>
