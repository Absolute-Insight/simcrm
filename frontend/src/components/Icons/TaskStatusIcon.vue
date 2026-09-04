<template>
  <component
    :is="GLYPH[status] ?? PhCircleDashed"
    v-bind="intrinsicProps('TaskStatusIcon')"
    class="text-ink-gray-7"
    :aria-label="status"
  />
</template>

<script setup>
import {
  PhArrowsClockwise,
  PhCheckCircle,
  PhCircle,
  PhCircleDashed,
  PhCircleHalf,
  PhXCircle,
} from '@phosphor-icons/vue'
import { intrinsicProps } from './_phosphor'

// The legacy glyphs read as a progress ladder: dashed ring (Backlog), empty
// ring (Todo), half-filled (In Progress), tick (Done), cross (Canceled).
// Phosphor carries that same ladder, so the semantics survive the swap.
//
// Key is 'Canceled' (one L) — that's the actual status value used across the
// app (src/utils/index.js options list, src/utils/callLog.js), matching what
// the legacy template checked. A double-L key would silently miss it.
const GLYPH = {
  Backlog: PhCircleDashed,
  Todo: PhCircle,
  'In Progress': PhCircleHalf,
  // the client moved it: neither done nor dropped, and worth counting as its own thing
  Rescheduled: PhArrowsClockwise,
  Done: PhCheckCircle,
  Canceled: PhXCircle,
}

defineProps({ status: { type: String, required: true } })
</script>
