<template>
  <Teleport v-if="showHeader" to="#app-header">
    <slot>
      <header
        class="flex h-[var(--v-toolbar-h)] items-center justify-between gap-2 sm:pl-5 pl-2"
      >
        <!-- the title gives way; the actions never do -->
        <div class="flex min-w-0 items-center gap-2 overflow-hidden">
          <slot name="left-header" />
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <slot name="right-header" class="flex items-center gap-2" />
        </div>
      </header>
    </slot>
  </Teleport>
</template>
<script setup>
import { ref, nextTick } from 'vue'

const showHeader = ref(false)

nextTick(() => {
  showHeader.value = true
})
</script>
