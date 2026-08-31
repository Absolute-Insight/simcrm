<template>
  <div class="grid place-items-center">
    <div
      class="h-3 w-3 rounded-full bg-current"
      :class="[COLOR[priority] ?? 'text-ink-gray-5', $attrs.class]"
    />
  </div>
</template>

<script setup>
defineOptions({ inheritAttrs: false })

// Was `({...}, $attrs.class)` — a comma expression, so the object was
// discarded and the priority colour never applied.
//
// Coloured via `bg-current` + an ink token, which is the convention every
// other status dot in the app already uses (IndicatorIcon is filled with
// currentColor and coloured by `text-ink-*-9` from the status stores). There
// is no `--surface-red-*` or `--surface-orange-*` ramp to reach for — the
// generated theme carries only `--surface-orange-1` and `--surface-amber-2`.
// Orange rather than yellow, and the -9 step: no amber step clears 4.5:1 on a
// light surface (AGENTS.md, Design system).
const COLOR = {
  High: 'text-ink-red-9',
  Medium: 'text-ink-orange-9',
  Low: 'text-ink-gray-5',
}

defineProps({ priority: { type: String, required: true } })
</script>
