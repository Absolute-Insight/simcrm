import { defineComponent, h, markRaw } from 'vue'

/**
 * A real <button> for `<component :is>`.
 *
 * The string 'button' handed to `<component :is>` is resolved as a component
 * name before it is treated as an element, and main.js registers frappe-ui's
 * Button globally — so 'button' resolved to that, and every drillable card
 * silently picked up a design-system button's inline-flex centering and
 * background on top of its own classes. This wrapper renders the actual
 * element and dodges the lookup; class, type, aria-label and click listeners
 * all reach it through attrs fallthrough.
 */
export const NativeButton = markRaw(
  defineComponent({
    name: 'NativeButton',
    setup(_, { slots }) {
      return () => h('button', null, slots.default?.())
    },
  }),
)
