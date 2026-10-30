<template>
  <div class="flex pr-3">
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
    <div id="app-header" class="flex-1" />
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
