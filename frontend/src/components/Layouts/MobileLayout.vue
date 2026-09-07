<template>
  <div class="flex h-screen w-screen">
    <MobileSidebar />
    <div
      class="v-lux-stage flex h-full flex-1 flex-col overflow-auto bg-surface-base"
    >
      <MobileAppHeader />
      <slot />
    </div>
    <!-- Mounted here rather than inside the drawer's AppSidebar (which mounts
         it on desktop): the drawer is itself a Dialog, and a Dialog nested in
         it would close with the drawer. -->
    <Settings />
    <GlobalModals />
  </div>
</template>
<script setup>
import MobileSidebar from '@/components/Mobile/MobileSidebar.vue'
import MobileAppHeader from '@/components/Mobile/MobileAppHeader.vue'
import GlobalModals from '@/components/Modals/GlobalModals.vue'
import Settings from '@/components/Settings/Settings.vue'
</script>
