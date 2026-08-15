<!--
  Skeleton — a content-shaped placeholder for the first paint of a panel.

  Reach for it when a resource is loading and you know roughly what shape the
  answer will be: a heading and two lines of prose, an avatar, a chart block.
  Shape it like the thing it replaces, at the same size and in the same place,
  so the swap to real content is a fade and not a jump.

  Do not reach for it for an action the user just triggered (that is a button
  `loading` state), for a list that may come back empty (that is EmptyState
  once it resolves), or for a fetch that may fail (pair it with ErrorState).

    <Skeleton v-if="deal.loading" shape="text" :lines="3" />
    <Skeleton shape="circle" width="2rem" />
    <Skeleton shape="block" height="12rem" />
-->
<template>
  <div
    class="v-skeleton"
    :class="`v-skeleton--${shape}`"
    v-bind="a11y"
    :style="rootStyle"
  >
    <template v-if="shape === 'text'">
      <div
        v-for="(lineWidth, i) in lineWidths"
        :key="i"
        class="v-skeleton__bar"
        :style="{ width: lineWidth, height: metrics.bar, borderRadius: radius }"
      />
    </template>
    <div
      v-else
      class="v-skeleton__bar"
      :style="{ width: '100%', height: '100%', borderRadius: radius }"
    />
  </div>
</template>

<script setup>
import { skeletonLineWidths } from '@/utils/skeletonShapes'
import { computed } from 'vue'

/* Bar thickness and row rhythm per text step. The bar is the cap height of the
   type it stands in for, not the full line box — a bar as tall as the line
   height reads as a filled block, which is the generic-grey-box look. */
const TEXT_METRICS = {
  sm: { bar: '0.5rem', row: '1rem' },
  base: { bar: '0.625rem', row: '1.25rem' },
  lg: { bar: '0.6875rem', row: '1.5rem' },
  xl: { bar: '0.875rem', row: '1.75rem' },
}

const props = defineProps({
  shape: {
    type: String,
    default: 'text',
    validator: (v) => ['text', 'block', 'circle'].includes(v),
  },
  // Text only. Multi-line renders a ragged right edge and a short last line.
  lines: { type: Number, default: 1 },
  // Any CSS length. Defaults to filling the container, except for circles.
  width: { type: String, default: '' },
  height: { type: String, default: '' },
  // Text only: which step of the type scale these lines stand in for.
  size: {
    type: String,
    default: 'base',
    validator: (v) => ['sm', 'base', 'lg', 'xl'].includes(v),
  },
  rounded: { type: String, default: '' },
  // Set on the one skeleton that represents the whole region, so screen
  // readers hear that something is coming. Others stay decorative.
  label: { type: String, default: '' },
})

const metrics = computed(() => TEXT_METRICS[props.size] || TEXT_METRICS.base)

const lineWidths = computed(() =>
  props.shape === 'text' ? skeletonLineWidths(props.lines) : [],
)

const radius = computed(() => {
  if (props.rounded) return props.rounded
  return props.shape === 'circle' ? '9999px' : '4px'
})

const rootStyle = computed(() => {
  if (props.shape === 'circle') {
    const diameter = props.width || props.height || '2rem'
    return { width: diameter, height: diameter }
  }
  if (props.shape === 'block') {
    return { width: props.width || '100%', height: props.height || '2.5rem' }
  }
  const gap = `calc(${metrics.value.row} - ${metrics.value.bar})`
  return { width: props.width || '100%', gap }
})

const a11y = computed(() =>
  props.label
    ? { role: 'status', 'aria-busy': 'true', 'aria-label': props.label }
    : { 'aria-hidden': 'true' },
)
</script>

<style scoped>
.v-skeleton {
  display: flex;
  flex-direction: column;

  /* The sheen must be lighter than the base in both modes, which means the two
     ramps are read in opposite directions — hence a full pair per theme rather
     than one pair and a tint. */
  --skeleton-base: var(--surface-gray-3);
  --skeleton-sheen: var(--surface-gray-1);

  /* Tied to the motion scale rather than a loose number, so a change to the
     app's tempo carries here too. Slower than any interaction timing: a
     shimmer at hover speed reads as agitation. */
  --skeleton-sweep: calc(var(--motion-slow) * 5);
}

[data-theme='dark'] .v-skeleton {
  --skeleton-base: var(--surface-gray-2);
  --skeleton-sheen: var(--surface-gray-4);
}

.v-skeleton__bar {
  flex: none;
  background-color: var(--skeleton-base);
}

@media (prefers-reduced-motion: no-preference) {
  .v-skeleton__bar {
    background-image: linear-gradient(
      90deg,
      transparent 20%,
      var(--skeleton-sheen) 50%,
      transparent 80%
    );
    background-repeat: no-repeat;
    background-size: 220% 100%;
    animation: v-skeleton-sweep var(--skeleton-sweep) var(--motion-ease)
      infinite;
  }

  /* Each line starts a little later than the one above it, so the sweep reads
     as one light source crossing a paragraph instead of bars blinking in
     unison. Capped at four steps — beyond that the stagger becomes a wave. */
  .v-skeleton--text > .v-skeleton__bar:nth-child(2) {
    animation-delay: calc(var(--skeleton-sweep) / -12);
  }
  .v-skeleton--text > .v-skeleton__bar:nth-child(3) {
    animation-delay: calc(var(--skeleton-sweep) / -6);
  }
  .v-skeleton--text > .v-skeleton__bar:nth-child(n + 4) {
    animation-delay: calc(var(--skeleton-sweep) / -4);
  }
}

/* The global reduced-motion rule in index.css crushes every animation to
   0.01ms, which would freeze the sweep gradient mid-stroke and leave a
   permanent bright streak. So the gradient itself is withheld here and the
   placeholder is a flat tint. */
@media (prefers-reduced-motion: reduce) {
  .v-skeleton__bar {
    background-image: none;
  }
}

@keyframes v-skeleton-sweep {
  from {
    background-position: 180% 0;
  }
  to {
    background-position: -80% 0;
  }
}
</style>
