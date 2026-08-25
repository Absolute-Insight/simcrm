<!--
  RadialGauge — a percentage that reads at arm's length.

  The same object-in-three-states contract as StatTile (loading skeleton,
  inline retry, resolved), and the same clickable-means-button rule. The ring
  is decoration for the number: the arc clamps to 0-100 while the text shows
  the server's value untouched, and the server's hint stays visible because a
  bare percentage is a number where an answer should be.
-->
<template>
  <component
    :is="clickable ? NativeButton : 'div'"
    :type="clickable ? 'button' : undefined"
    class="v-glass group flex w-full items-center gap-5 rounded-6 p-4 text-left"
    :class="
      clickable
        ? 'v-glass-hover cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'
        : ''
    "
    :aria-label="clickable ? drilldownLabel : undefined"
    @click="clickable && $emit('drill')"
  >
    <Skeleton
      v-if="loading"
      shape="circle"
      height="6.5rem"
      width="6.5rem"
      :label="__('Loading {0}', [label])"
    />
    <svg v-else-if="!error" width="104" height="104" viewBox="0 0 140 140">
      <defs>
        <linearGradient :id="gradientId" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#21abfb" />
          <stop offset="1" stop-color="#5b5fe8" />
        </linearGradient>
      </defs>
      <circle
        cx="70"
        cy="70"
        r="58"
        fill="none"
        stroke="var(--v-gauge-track)"
        stroke-width="10"
        aria-hidden="true"
      />
      <circle
        v-if="ring.pct > 0"
        cx="70"
        cy="70"
        r="58"
        fill="none"
        :stroke="`url(#${gradientId})`"
        stroke-width="10"
        stroke-linecap="round"
        :stroke-dasharray="ring.dasharray"
        transform="rotate(-90 70 70)"
        aria-hidden="true"
      />
      <text
        x="70"
        y="76"
        text-anchor="middle"
        class="fill-ink-gray-9 font-display"
        font-size="26"
        font-weight="600"
      >
        {{ display }}
      </text>
    </svg>

    <div v-if="error" class="flex min-w-0 flex-1 flex-col gap-1">
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
    <div v-else class="flex min-w-0 flex-1 flex-col gap-1">
      <span class="v-kpi-label text-ink-gray-5">{{ label }}</span>
      <span v-if="hint" class="text-sm text-ink-gray-5">{{ hint }}</span>
      <span
        v-if="deltaDisplay"
        class="text-sm font-medium"
        :class="{
          'text-ink-green-9': tone === 'positive',
          'text-ink-red-9': tone === 'negative',
          'text-ink-gray-5': tone === 'neutral',
        }"
      >
        {{ deltaDisplay }}
      </span>
      <span v-if="unfilteredNote" class="text-sm text-ink-orange-9">
        {{ unfilteredNote }}
      </span>
    </div>
  </component>
</template>

<script setup>
import Skeleton from '@/components/ui/Skeleton.vue'
import { deltaTone } from '@/utils/dashboardHome'
import { formatDelta, ringDash } from '@/utils/gauge'
import { computed, defineComponent, h, markRaw, useId } from 'vue'

/* Same trap StatTile documents: the string 'button' handed to
   `<component :is>` resolves to frappe-ui's globally registered Button, so
   the real element needs a wrapper that dodges the name lookup. */
const NativeButton = markRaw(
  defineComponent({
    name: 'RadialGaugeNativeButton',
    setup(_, { slots }) {
      return () => h('button', null, slots.default?.())
    },
  }),
)

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: null },
  suffix: { type: String, default: '%' },
  hint: { type: String, default: '' },
  delta: { type: [Number, String], default: 0 },
  deltaSuffix: { type: String, default: '' },
  negativeIsBetter: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  error: { type: [Object, String, Error], default: null },
  retry: { type: Function, default: null },
  drilldownLabel: { type: String, default: '' },
  unfilteredNote: { type: String, default: '' },
})

defineEmits(['drill'])

const gradientId = `gauge-grad-${useId()}`

const clickable = computed(
  () => Boolean(props.drilldownLabel) && !props.loading && !props.error,
)

const ring = computed(() => ringDash(props.value, 58))

const display = computed(() => {
  if (props.value === null || props.value === undefined || props.value === '') {
    return '—'
  }
  return `${props.value}${props.suffix}`
})

const tone = computed(() => deltaTone(props.delta, props.negativeIsBetter))
const deltaDisplay = computed(() => formatDelta(props.delta, props.deltaSuffix))
</script>
