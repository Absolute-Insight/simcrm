<template>
  <TextInput
    ref="inputRef"
    :value="displayValue"
    v-bind="$attrs"
    @focus="handleFocus"
    @blur="isFocused = false"
  />
</template>
<script setup>
import { TextInput } from 'frappe-ui'
import { ref, computed, nextTick } from 'vue'

// TextInput renders `description` itself, and $attrs is bound to it explicitly
// below. Rendering a second copy here showed every numeric field's description
// twice; letting TextInput own it also associates the text with the input for
// screen readers, which the local copy never did. With the paragraph gone this
// is a single-root component, so attrs must not also be applied automatically.
defineOptions({ inheritAttrs: false })

const props = defineProps({
  value: { type: [String, Number], default: '' },
  formattedValue: { type: [String, Number], default: '' },
})

const isFocused = ref(false)
const inputRef = ref(null)

function handleFocus() {
  isFocused.value = true

  nextTick(() => {
    if (inputRef.value) {
      inputRef.value.el?.select()
    }
  })
}

const displayValue = computed(() => {
  return isFocused.value ? props.value : props.formattedValue || props.value
})
</script>
