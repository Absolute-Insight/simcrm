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
    :is="clickable ? NativeButton : 'div'"
    :type="clickable ? 'button' : undefined"
    class="v-stat-tile v-glass group relative flex min-h-[6.5rem] w-full flex-col justify-between gap-2 rounded-6 p-4 text-left"
    :class="[
      clickable
        ? 'v-glass-hover cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'
        : '',
      accent === 'danger' ? '!border-[rgba(216,77,77,0.35)]' : '',
    ]"
    :aria-label="clickable ? drilldownLabel : undefined"
    @click="clickable && $emit('drill')"
  >
    <div class="flex items-start justify-between gap-2">
      <Tooltip :text="tooltip || ''" :disabled="!tooltip">
        <span
          class="v-kpi-label"
          :class="accent === 'danger' ? 'text-ink-red-9' : 'text-ink-gray-5'"
          >{{ label }}</span
        >
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
          class="self-start rounded-4 text-sm text-ink-gray-5 underline underline-offset-2 hover:text-ink-gray-8 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          @click.stop="retry"
        >
          {{ __('Try again') }}
        </button>
      </div>
    </div>

    <div v-else class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span
        class="font-display text-[38px] font-semibold leading-[1.05] tracking-tight text-ink-gray-9"
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
      <!-- Not the hint: a hint explains the number, this says the number is not
           the one the filter asked for. Styled apart so it cannot be skimmed as
           supporting detail. -->
      <span v-if="unfilteredNote" class="w-full text-sm text-ink-orange-9">
        {{ unfilteredNote }}
      </span>
    </div>
  </component>
</template>

<script setup>
import LucideArrowUpRight from '~icons/lucide/arrow-up-right'
import LucideTriangleAlert from '~icons/lucide/alert-triangle'
import Skeleton from '@/components/ui/Skeleton.vue'
import { deltaTone } from '@/utils/dashboardHome'
import { formatDelta } from '@/utils/gauge'
import { formatCell } from '@/utils/reportExport'
import { Tooltip } from 'frappe-ui'
import { computed, defineComponent, h, markRaw } from 'vue'

/* Not the string 'button': a string passed to `<component :is>` is resolved
   as a component name before it is treated as an element, and main.js
   registers frappe-ui's Button globally — so 'button' resolved to that, and
   every drillable tile silently picked up a design-system button's
   inline-flex centering and background on top of its own classes. A wrapper
   that renders the real element dodges the lookup; class, type, aria-label
   and the click listener all reach it through attrs fallthrough. */
const NativeButton = markRaw(
  defineComponent({
    name: 'StatTileNativeButton',
    setup(_, { slots }) {
      return () => h('button', null, slots.default?.())
    },
  }),
)

const props = defineProps({
  // Already translated by the caller: half these labels come from the server,
  // which translates its own, and runtime text must never reach __().
  label: { type: String, required: true },
  value: { type: [Number, String], default: null },
  prefix: { type: String, default: '' },
  suffix: { type: String, default: '' },
  // A second line under the number — "3 of 7 done", "vs 120,000 quota".
  hint: { type: String, default: '' },
  // Set when a filter is active that this tile cannot honour. Quota attainment
  // is per rep and rep plans have no territory, so both keep answering for the
  // whole company; saying nothing would leave them looking scoped like their
  // neighbours.
  unfilteredNote: { type: String, default: '' },
  tooltip: { type: String, default: '' },
  delta: { type: [Number, String], default: 0 },
  deltaSuffix: { type: String, default: '' },
  negativeIsBetter: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  error: { type: [Object, String, Error], default: null },
  retry: { type: Function, default: null },
  // Where clicking lands, for the accessible name. Empty means not clickable.
  drilldownLabel: { type: String, default: '' },
  // 'danger' tints the tile's frame and label red: the one tile whose number
  // being high is itself the alert (critical deals).
  accent: { type: String, default: '' },
})

defineEmits(['drill'])

const clickable = computed(
  () => Boolean(props.drilldownLabel) && !props.loading && !props.error,
)

/* Grouped, in the reader's locale — `1,234`, not `1234`. These tiles sit
   directly above a chart grid that compacts the same magnitudes to `1.2K`, and
   the delta beside them was already carefully formatted, so the headline number
   was the one unformatted figure on the page. Nothing is visibly wrong today
   because every value arrives pre-rounded from the server; the moment that
   stops, a raw float lands in the largest type on the dashboard.

   Only actual numbers are touched. A tile whose value is already a string has
   been formatted by its caller — percentages, ratios, "3 of 7" — and
   reformatting it would undo that. */
const display = computed(() => {
  if (props.value === null || props.value === undefined || props.value === '') {
    return '—'
  }
  const number = typeof props.value === 'number' ? props.value : null
  const body =
    number !== null && Number.isFinite(number)
      ? formatCell(number, 'number')
      : props.value
  return `${props.prefix}${body}${props.suffix}`
})

const tone = computed(() => deltaTone(props.delta, props.negativeIsBetter))

const deltaDisplay = computed(() => formatDelta(props.delta, props.deltaSuffix))
</script>
