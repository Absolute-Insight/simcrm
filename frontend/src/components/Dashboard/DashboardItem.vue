<template>
  <div class="h-full w-full">
    <div
      v-if="item.type == 'number_chart'"
      class="v-number-card flex h-full w-full rounded shadow overflow-hidden cursor-pointer"
    >
      <Tooltip :text="__(item.data.tooltip)">
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
      class="rounded bg-surface-base h-full overflow-hidden text-ink-gray-5 flex items-center justify-center"
      :class="editing ? 'border border-dashed border-outline-gray-2' : ''"
    >
      {{ editing ? __('Spacer') : '' }}
    </div>
    <div
      v-else-if="item.type == 'axis_chart'"
      class="h-full w-full rounded-md bg-surface-base shadow"
    >
      <p v-if="blankReason" :class="blankClass">{{ blankReason }}</p>
      <AxisChart v-else-if="item.data" :config="themed" />
    </div>
    <div
      v-else-if="item.type == 'donut_chart'"
      class="h-full w-full rounded-md bg-surface-base shadow overflow-hidden"
    >
      <p v-if="blankReason" :class="blankClass">{{ blankReason }}</p>
      <DonutChart v-else-if="item.data" :config="themed" />
    </div>
  </div>
</template>
<script setup>
import { withVectoraTheme } from '@/utils/chartTheme'
import { AxisChart, DonutChart, NumberChart, Tooltip } from 'frappe-ui'
import { computed } from 'vue'

const props = defineProps({
  index: { type: Number, required: true },
  item: { type: Object, required: true },
  editing: { type: Boolean, default: false },
})

// the server returns the chart's shape and data; its colours are a display
// decision, so they are applied here rather than travelling over the wire
const themed = computed(() => withVectoraTheme(props.item.data))

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
</script>
