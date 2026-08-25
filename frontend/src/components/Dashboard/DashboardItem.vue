<template>
  <div class="h-full w-full">
    <div
      v-if="item.type == 'number_chart'"
      class="v-number-card v-glass flex h-full w-full rounded-4 overflow-hidden cursor-pointer"
    >
      <Tooltip :text="unfilteredNote || __(item.data.tooltip)">
        <NumberChart
          v-if="item.data"
          :key="index"
          class="!items-start"
          :config="item.data"
        />
      </Tooltip>
    </div>
    <div
      v-else-if="item.type == 'spacer'"
      class="rounded-4 bg-surface-base h-full overflow-hidden text-ink-gray-5 flex items-center justify-center"
      :class="editing ? 'border border-dashed border-outline-gray-2' : ''"
    >
      {{ editing ? __('Spacer') : '' }}
    </div>
    <div
      v-else-if="item.type == 'axis_chart'"
      class="v-glass relative h-full w-full rounded-5"
    >
      <p v-if="unfilteredNote" :class="noteClass">{{ unfilteredNote }}</p>
      <p v-if="blankReason" :class="blankClass">{{ blankReason }}</p>
      <AxisChart v-else-if="item.data" :config="themed" />
    </div>
    <div
      v-else-if="item.type == 'donut_chart'"
      class="v-glass relative h-full w-full rounded-5 overflow-hidden"
    >
      <p v-if="unfilteredNote" :class="noteClass">{{ unfilteredNote }}</p>
      <p v-if="blankReason" :class="blankClass">{{ blankReason }}</p>
      <DonutChart v-else-if="item.data" :config="themed" />
    </div>
  </div>
</template>
<script setup>
import { applyLuxChartTheme, useIsDark } from '@/utils/chartTheme'
import { Tooltip } from 'frappe-ui'
// parked in experimental for v1 (frappe-ui migration doc)
import { AxisChart, DonutChart, NumberChart } from 'frappe-ui/experimental'
import { computed } from 'vue'

const props = defineProps({
  index: { type: Number, required: true },
  item: { type: Object, required: true },
  editing: { type: Boolean, default: false },
})

// the server returns the chart's shape and data; its colours are a display
// decision, so they are applied here rather than travelling over the wire —
// and re-applied live when the theme flips, since the ref below tracks it
const dark = useIsDark()
const themed = computed(() => applyLuxChartTheme(props.item.data, dark.value))

/**
 * Why this chart is blank, when the aggregate knows why.
 *
 * A chart with nothing in it, sitting beside tiles showing real money, reads as
 * a broken widget. Only the function that produced no rows can tell "no deals
 * matched this period" from "forecasting is switched off", so it says so on the
 * payload and this renders it instead of an empty plot.
 */
const blankReason = computed(() => props.item.data?.emptyState || '')
const blankClass =
  'flex h-full w-full items-center justify-center p-6 text-center text-sm text-ink-gray-5'

/* A territory filter that quietly does not reach a chart is worse than no
   filter: quota attainment is per rep and rep plans have no territory, so those
   keep answering for the whole company. The server says which charts it reached
   (`territory_filtered`), and the ones it did not say so on their face rather
   than sitting silently beside filtered neighbours looking equally scoped. */
const unfilteredNote = computed(() => {
  const data = props.item.data
  if (!data?.territory || data.territory_filtered) return ''
  return __('Not filtered by {0} — this figure covers everyone.', [
    data.territory,
  ])
})
const noteClass =
  'absolute right-3 top-2 z-10 max-w-[70%] truncate text-xs text-ink-orange-9'
</script>
