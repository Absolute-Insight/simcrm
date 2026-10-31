import { defineComponent, h } from 'vue'

/**
 * A stub child for a component test: renders its default slot and records the
 * attrs (props and listeners) it was last rendered with under `state.children`,
 * so a test can read what the parent passed and drive it the way the real
 * child would (`state.children.SortBy.onUpdate('creation desc')`).
 */
export function recorder(name, state) {
  return defineComponent({
    name,
    inheritAttrs: false,
    setup(_, { attrs, slots }) {
      return () => {
        state.children[name] = attrs
        return h('div', { 'data-stub': name }, slots.default?.())
      }
    },
  })
}
