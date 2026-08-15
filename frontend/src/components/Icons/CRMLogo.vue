<template>
  <svg
    width="300"
    height="300"
    viewBox="0 0 300 300"
    fill="none"
    role="img"
    :aria-hidden="decorative || undefined"
    xmlns="http://www.w3.org/2000/svg"
  >
    <title v-if="!decorative">Vectora</title>
    <defs>
      <linearGradient
        :id="gradientId"
        x1="44"
        y1="60"
        x2="256"
        y2="80"
        gradientUnits="userSpaceOnUse"
      >
        <stop offset="0" stop-color="#21ABFB" />
        <stop offset="0.55" stop-color="#5B5FE8" />
        <stop offset="1" stop-color="#DF5FEB" />
      </linearGradient>
    </defs>
    <path
      d="M72 56L150 236L228 56"
      :stroke="`url(#${gradientId})`"
      stroke-width="52"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </svg>
</template>

<script setup>
import { useId } from 'vue'

defineProps({
  // Set where the product is already named in text next to the mark, so a
  // screen reader does not announce "Vectora Vectora".
  decorative: { type: Boolean, default: false },
})

// SVG gradient ids are document-global: two instances of a fixed id make the
// second mark reference the first one's (possibly unmounted) gradient node.
const gradientId = `vectora-v-gradient-${useId()}`
</script>
