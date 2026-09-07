<!--
  CheckSwitch — frappe-ui's Switch bound to a Frappe Check field.

  A Check is stored 0/1, and reka-ui's SwitchRoot (under frappe-ui's Switch)
  compares `modelValue === true` strictly. Bound to `1` the track renders on,
  `aria-checked` reads false, and the first click sets `true` — no visible
  change, a false "enabled" toast — so only the second click turns it off.
  AutomationRules.vue fixed one switch by hand; this is that fix as a component.

  Coerces `!!` in and `1 : 0` out, so the document keeps the integer the server
  expects and the control agrees with what it shows. Everything else — size,
  label, description, disabled, class, click listeners — passes straight
  through to Switch.

    <CheckSwitch v-model="settings.doc.enable_forecasting" size="sm" />
-->
<template>
  <Switch
    v-bind="$attrs"
    :model-value="!!modelValue"
    @update:model-value="emit('update:modelValue', $event ? 1 : 0)"
  />
</template>

<script setup>
import { Switch } from 'frappe-ui'

defineOptions({ inheritAttrs: false })

defineProps({
  // 0/1 from the server; true/false or '0'/'1' from a form that was bound raw.
  modelValue: { type: [Number, Boolean, String, null], default: 0 },
})

const emit = defineEmits(['update:modelValue'])
</script>
