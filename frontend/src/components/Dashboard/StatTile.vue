<!--
  StatTile — one number on the dashboard, and the way to the records behind it.

  Every tile is the same object in three states: loading (a skeleton the size of
  the numeral it stands in for), failed (an inline retry, never a blank card),
  and resolved. A tile with a drill-down renders as a button and says where it
  goes; one without renders as a plain card, because a cursor that changes over
  something unclickable is a lie the interface tells cheaply.
-->
<template>
  <component
    :is="clickable ? 'button' : 'div'"
    :type="clickable ? 'button' : undefined"
    class="v-stat-tile group relative flex min-h-[6.5rem] w-full flex-col justify-between gap-2 rounded-lg border border-outline-gray-1 bg-surface-elevation-2 p-4 text-left"
    :class="
      clickable
        ? 'cursor-pointer hover:border-outline-gray-2 hover:shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'
        : ''
    "
    :aria-label="clickable ? drilldownLabel : undefined"
    @click="clickable && $emit('drill')"
  >
    <div class="flex items-start justify-between gap-2">
      <Tooltip :text="tooltip || ''" :disabled="!tooltip">
        <span class="text-sm text-ink-gray-6">{{ label }}</span>
      </Tooltip>
      <LucideArrowUpRight
        v-if="clickable"
        class="size-4 shrink-0 text-ink-gray-4 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
        aria-hidden="true"
      />
    </div>

    <Skeleton
      v-if="loading"
      shape="block"
      height="1.75rem"
      width="55%"
      :label="__('Loading {0}', [label])"
    />

    <!-- A tile that failed says so in its own footprint. The full ErrorState is
         a page-sized apology; inside a 100px card it would push the grid
         around, so the message is one line and the retry is the icon. -->
    <div v-else-if="error" class="flex items-start gap-2">
      <LucideTriangleAlert
        class="mt-0.5 size-4 shrink-0 text-ink-red-9"
        aria-hidden="true"
      />
      <div class="flex min-w-0 flex-1 flex-col gap-1">
        <span class="text-sm text-ink-gray-7">{{
          __('Could not load this')
        }}</span>
        <button
          v-if="retry"
          type="button"
          class="self-start rounded text-sm text-ink-gray-5 underline underline-offset-2 hover:text-ink-gray-8 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          @click.stop="retry"
        >
          {{ __('Try again') }}
        </button>
      </div>
    </div>

    <div v-else class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span
        class="font-display text-2xl font-medium tracking-tight text-ink-gray-9"
      >
        {{ display }}
      </span>
      <span
        v-if="delta"
        class="text-sm font-medium"
        :class="{
          'text-ink-green-9': tone === 'positive',
          'text-ink-red-9': tone === 'negative',
          'text-ink-gray-5': tone === 'neutral',
        }"
      >
        {{ deltaDisplay }}
      </span>
      <span v-if="hint" class="w-full text-sm text-ink-gray-5">{{ hint }}</span>
    </div>
  </component>
</template>

<script setup>
import LucideArrowUpRight from '~icons/lucide/arrow-up-right'
import LucideTriangleAlert from '~icons/lucide/alert-triangle'
import Skeleton from '@/components/ui/Skeleton.vue'
import { deltaTone } from '@/utils/dashboardHome'
import { Tooltip } from 'frappe-ui'
import { computed } from 'vue'

const props = defineProps({
  // Already translated by the caller: half these labels come from the server,
  // which translates its own, and runtime text must never reach __().
  label: { type: String, required: true },
  value: { type: [Number, String], default: null },
  prefix: { type: String, default: '' },
  suffix: { type: String, default: '' },
  // A second line under the number — "3 of 7 done", "vs 120,000 quota".
  hint: { type: String, default: '' },
  tooltip: { type: String, default: '' },
  delta: { type: [Number, String], default: 0 },
  deltaSuffix: { type: String, default: '' },
  negativeIsBetter: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  error: { type: [Object, String, Error], default: null },
  retry: { type: Function, default: null },
  // Where clicking lands, for the accessible name. Empty means not clickable.
  drilldownLabel: { type: String, default: '' },
})

defineEmits(['drill'])

const clickable = computed(
  () => Boolean(props.drilldownLabel) && !props.loading && !props.error,
)

const display = computed(() => {
  if (props.value === null || props.value === undefined || props.value === '') {
    return '—'
  }
  return `${props.prefix}${props.value}${props.suffix}`
})

const tone = computed(() => deltaTone(props.delta, props.negativeIsBetter))

// Deltas arrive as raw ratios — a month that went from 1 deal to 18 produces
// 1721.4285714285716. Sixteen significant figures of period-over-period change
// is noise, and it wrecks the tile's layout; one decimal is as much as anyone
// reads, and past 999% the exact figure has stopped meaning anything anyway.
const deltaDisplay = computed(() => {
  const value = Number(props.delta) || 0
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  const magnitude = Math.abs(value)
  if (magnitude >= 1000) return `${sign}999+${props.deltaSuffix}`
  const rounded =
    magnitude >= 100 ? Math.round(magnitude) : Math.round(magnitude * 10) / 10
  return `${sign}${rounded}${props.deltaSuffix}`
})
</script>
