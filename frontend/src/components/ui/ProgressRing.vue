<template>
  <!-- frappe-ui v1 deleted CircularProgressBar with no circular replacement
       (migration doc: "use Progress for a linear bar, or render the arc
       yourself"). This is the arc, kept to the prop surface the uploader
       used: step/totalSteps and an optional percentage readout. -->
  <div
    class="relative inline-flex items-center justify-center"
    role="progressbar"
    :aria-valuenow="percent"
    aria-valuemin="0"
    aria-valuemax="100"
  >
    <svg :width="size" :height="size" viewBox="0 0 36 36" class="-rotate-90">
      <circle
        cx="18"
        cy="18"
        :r="radius"
        fill="none"
        class="stroke-outline-gray-2"
        :stroke-width="stroke"
      />
      <circle
        cx="18"
        cy="18"
        :r="radius"
        fill="none"
        stroke="currentColor"
        :stroke-width="stroke"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="circumference * (1 - percent / 100)"
        class="transition-[stroke-dashoffset]"
      />
    </svg>
    <span
      v-if="showPercentage"
      class="absolute text-[9px] tabular-nums text-ink-gray-6"
    >
      {{ percent }}
    </span>
  </div>
</template>
<script setup>
import { computed } from 'vue'

const props = defineProps({
  step: { type: Number, default: 0 },
  totalSteps: { type: Number, default: 100 },
  size: { type: Number, default: 24 },
  stroke: { type: Number, default: 4 },
  showPercentage: { type: Boolean, default: false },
})

const radius = 16
const circumference = 2 * Math.PI * radius
const percent = computed(() => {
  if (!props.totalSteps) return 0
  return Math.max(
    0,
    Math.min(100, Math.round((props.step / props.totalSteps) * 100)),
  )
})
</script>
