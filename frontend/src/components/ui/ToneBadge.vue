<!--
  A Badge that can also be orange.

  frappe-ui's Badge supports gray, blue, green, amber, red and violet. The
  design language asks for orange on warnings, and the two ways of getting one
  out of the shipped component both fail:

  - `theme="orange"` is not in Badge's lookup table, so `resolvePropValue`
    degrades it to gray. The badge renders, silently, with no tone at all.
  - `theme="amber"` renders, but `text-ink-amber-7` on `bg-surface-amber-2`
    measures 3.55:1 on a light surface — under the 4.5:1 AA floor for text this
    size. This is the case AGENTS.md is describing when it says to use orange
    and not amber.

  Orange is drawn here instead, from the same two tokens the dashboard and
  report notices already use (`bg-surface-orange-1` / `text-ink-orange-9`,
  measured at 10.09:1 light and 11.88:1 dark). Drawing it rather than
  appending a class to Badge keeps the result off the cascade: an appended
  `text-ink-orange-9` only beats Badge's own `text-ink-*` because the orange
  utility happens to be emitted later in the stylesheet, which nothing tests
  and a dependency bump could reorder.

  Every other tone is Badge's own and is passed straight through, so this stays
  a drop-in. When frappe-ui ships an orange theme, delete the first branch and
  the call sites keep working.
-->
<template>
  <span v-if="theme === 'orange'" :class="orangeClasses">
    <span
      v-if="$slots.prefix"
      class="inline-flex shrink-0 items-center justify-center"
      :class="iconSize"
    >
      <slot name="prefix" />
    </span>
    <slot>{{ label?.toString() }}</slot>
    <span
      v-if="$slots.suffix"
      class="inline-flex shrink-0 items-center justify-center"
      :class="iconSize"
    >
      <slot name="suffix" />
    </span>
  </span>
  <Badge v-else :theme="theme" :size="size" :variant="variant" :label="label">
    <template v-if="$slots.prefix" #prefix><slot name="prefix" /></template>
    <template v-if="$slots.default" #default><slot /></template>
    <template v-if="$slots.suffix" #suffix><slot name="suffix" /></template>
  </Badge>
</template>

<script setup>
import { computed } from 'vue'
import { Badge } from 'frappe-ui'

const props = defineProps({
  /** Badge's own themes, plus 'orange'. */
  theme: { type: String, default: 'gray' },
  size: { type: String, default: 'md' },
  variant: { type: String, default: 'subtle' },
  label: { type: [String, Number, Object], default: undefined },
})

// Mirrors Badge's own structure and size scale so an orange badge sits at the
// same height and rhythm as every other one on the screen.
const BASE =
  'inline-flex select-none items-center gap-1 overflow-clip rounded-full whitespace-nowrap'

const SIZES = {
  sm: 'h-4 px-1.5 text-xs',
  md: 'h-5 px-1.5 text-xs',
  lg: 'h-6 px-2 text-[13px] tracking-[0.02em]',
}

// `-9` is the readable step in both themes; the lighter steps are background
// tints, not text colours. Solid is deliberately absent — no orange surface
// step carries white at 4.5:1 — so it resolves to the filled subtle treatment
// rather than rendering an unreadable badge.
const VARIANTS = {
  solid: 'text-ink-orange-9 bg-surface-orange-1',
  subtle: 'text-ink-orange-9 bg-surface-orange-1',
  outline: 'text-ink-orange-9 border border-outline-orange-2',
  ghost: 'text-ink-orange-9',
}

const orangeClasses = computed(() => [
  BASE,
  SIZES[props.size] ?? SIZES.md,
  VARIANTS[props.variant] ?? VARIANTS.subtle,
])

const iconSize = computed(() => (props.size === 'lg' ? 'size-3' : 'size-2.5'))
</script>
