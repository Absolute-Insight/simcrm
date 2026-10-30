// A stand-in for 'frappe-ui' in the telephony component tests: frappe-ui's own
// resource layer (createResource and its cache, which some of these bugs live
// in), with `call`, `toast` and the widgets replaced by recorders and plain
// elements a test can find and click.
//
//   vi.mock('frappe-ui', () => import('./telephony/frappeUi.js'))
import { h } from 'vue'

export { createResource } from '../../../node_modules/frappe-ui/src/resources/resources.js'
export { setConfig } from '../../../node_modules/frappe-ui/src/utils/config.ts'

export const calls = []
export const toasts = []
// what a `call(method, args)` answers; a test replaces it
export const answers = { call: () => Promise.resolve({}) }

export function call(method, args) {
  calls.push({ method, args })
  return answers.call(method, args)
}

export const toast = {
  error: (message) => toasts.push(['error', message]),
  warning: (message) => toasts.push(['warning', message]),
  success: (message) => toasts.push(['success', message]),
  info: (message) => toasts.push(['info', message]),
}

export function resetRecorders() {
  calls.length = 0
  toasts.length = 0
  answers.call = () => Promise.resolve({})
}

const widget = (name, tag = 'div') => ({
  name,
  inheritAttrs: false,
  render() {
    const { label, tooltip, onClick } = this.$attrs
    return h(
      tag,
      {
        class: `stub-${name}`,
        'data-label': label,
        'data-tooltip': tooltip,
        onClick,
      },
      [label ?? null, this.$slots.default?.()],
    )
  },
})

export const Button = widget('Button', 'button')
export const Avatar = widget('Avatar')
export const Tooltip = widget('Tooltip')
export const Dropdown = widget('Dropdown')
export const DateTimePicker = widget('DateTimePicker')
export const ErrorMessage = widget('ErrorMessage')
export const Combobox = widget('Combobox')
export const Dialog = {
  name: 'Dialog',
  inheritAttrs: false,
  props: ['open', 'title', 'actions'],
  render() {
    return this.open
      ? h('div', { class: 'stub-Dialog' }, this.$slots.default?.())
      : null
  },
}

// Every FormControl mounted, newest last, so a test can type into one.
export const formControls = []
export const FormControl = {
  name: 'FormControl',
  inheritAttrs: false,
  props: ['modelValue', 'label', 'placeholder'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    formControls.push({ props, type: (v) => emit('update:modelValue', v) })
    return () =>
      h('input', { class: 'stub-FormControl', value: props.modelValue ?? '' })
  },
}
