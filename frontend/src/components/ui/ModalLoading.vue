<!--
  ModalLoading — what stands in for a dialog whose code is still on its way.

  A dialog loaded on first open has nothing to draw until its chunk arrives.
  This is drawn in its place, by lazyComponent, and only once the load has
  taken long enough to be noticed. It does not take clicks: the page under it
  is still the page.
-->
<template>
  <div
    class="pointer-events-none fixed inset-0 z-50 grid place-items-center"
    role="status"
    :aria-label="__('Loading')"
  >
    <div
      class="rounded-full border border-outline-gray-2 bg-surface-elevation-1 p-3 shadow-xl"
    >
      <LoadingIndicator class="size-5 text-ink-gray-6" />
    </div>
  </div>
</template>

<script setup>
import { LoadingIndicator } from 'frappe-ui'
</script>
