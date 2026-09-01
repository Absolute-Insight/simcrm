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
// currentColor and coloured by `text-ink-*-9` from the status stores). But
// this dot is a non-text graphic, not text on a surface — the -9 step is a
// *text*-legibility ladder (AGENTS.md, Design system) tuned to sit far above
// the 4.5:1 text floor, which in practice means it bottoms out very dark in
// light theme: red-9 (#6b1515) and orange-9 (#6b2711) are both near-black
// maroon/brown at 12px and read as the same colour. A non-text graphic only
// needs the 3:1 UI-graphics floor, so this reaches for -6 instead: still >=
// 3:1 against the row surface in both themes (measured: red-6 8.9:1 light /
// 5.4:1 dark, orange-6 7.2:1 light / 4.7:1 dark against the list card's own
// background — see the design brief), and at -6 both ramps keep enough
// chroma that red and orange read as clearly different hues rather than
// converging on near-black. Orange rather than amber/yellow — no amber step
// clears the floor on a light surface (AGENTS.md, Design system).
const COLOR = {
  High: 'text-ink-red-6',
  Medium: 'text-ink-orange-6',
  Low: 'text-ink-gray-5',
}

defineProps({ priority: { type: String, required: true } })
</script>
