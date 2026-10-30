import { createApp, h, nextTick } from 'vue'

/**
 * Mount a single-file component into happy-dom for a component test.
 *
 * The repo has no @vue/test-utils; createApp is enough for what these tests
 * check (rendered DOM, emitted events, calls the component makes). `stubs`
 * registers global components by name, the way main.js registers frappe-ui's.
 *
 *   const { el, vm, emitted, unmount } = mount(MyModal, { props: { show: true } })
 */
export function mount(
  component,
  { props = {}, slots = {}, stubs = {}, plugins = [] } = {},
) {
  const emitted = {}
  const listeners = {}
  for (const name of component.emits
    ? Object.keys(normaliseEmits(component.emits))
    : []) {
    const key = 'on' + name[0].toUpperCase() + name.slice(1)
    listeners[key] = (...args) => (emitted[name] ||= []).push(args)
  }
  let vm
  const app = createApp({
    render: () =>
      h(component, { ...listeners, ...props, ref: (r) => (vm = r) }, slots),
  })
  for (const [name, stub] of Object.entries(stubs)) app.component(name, stub)
  for (const plugin of plugins) app.use(...[].concat(plugin))
  const el = document.createElement('div')
  document.body.appendChild(el)
  app.mount(el)
  return {
    el,
    get vm() {
      return vm
    },
    emitted,
    nextTick,
    unmount() {
      app.unmount()
      el.remove()
    },
  }
}

function normaliseEmits(emits) {
  return Array.isArray(emits)
    ? Object.fromEntries(emits.map((e) => [e, null]))
    : emits
}
