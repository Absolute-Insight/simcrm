// A stand-in for 'frappe-ui/experimental': a TextEditor a test can type into.
//
//   vi.mock('frappe-ui/experimental', () => import('./telephony/experimental.js'))
import { h } from 'vue'

// Every TextEditor mounted, newest last.
export const editors = []

export const TextEditor = {
  name: 'TextEditor',
  inheritAttrs: false,
  props: ['content', 'placeholder'],
  emits: ['change'],
  setup(props, { emit }) {
    editors.push({ props, type: (value) => emit('change', value) })
    return () => h('div', { class: 'stub-TextEditor' })
  },
}
