<template>
  <!-- Sprite-backed stand-in for frappe-ui's removed FeatherIcon (ADR-0008).
       Renders the same name from the injected lucide sprite — lucide is a
       superset of feather — with the classic stroke geometry, so
       @framework/ui components that still say `<FeatherIcon name="x">`
       keep rendering until upstream migrates. -->
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.5"
    stroke-linecap="round"
    stroke-linejoin="round"
    class="shrink-0"
    aria-hidden="true"
  >
    <use :href="`#${String(name).replace(/^lucide-/, '')}`" />
  </svg>
</template>
<script setup>
defineProps({ name: { type: String, required: true } })
</script>
