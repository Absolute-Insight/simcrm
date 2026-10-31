import { afterEach } from 'vitest'
import { camelize, createApp, h, nextTick, toHandlerKey } from 'vue'

const mounted = new Set()

// A test that throws before its own unmount() would otherwise leave the app,
// and anything it teleported into <body>, for the next test in the file.
afterEach(() => {
  for (const wrapper of [...mounted]) wrapper.unmount()
})

/**
 * Mount a single-file component into happy-dom for a component test.
 *
 * The repo has no @vue/test-utils; createApp is enough for what these tests
 * check (rendered DOM, emitted events, calls the component makes). `stubs`
 * registers global components by name, the way main.js registers frappe-ui's.
 * Templates get `__()` from tests/setup.js unless a plugin installs its own.
 * A handler passed in `props` runs as well as the emit capture, not instead.
 *
 *   const { el, vm, emitted, unmount } = mount(MyModal, { props: { show: true } })
 */
export function mount(
  component,
  { props = {}, slots = {}, stubs = {}, plugins = [] } = {},
) {
  const emitted = {}
  const handlers = { ...props }
  for (const name of component.emits
    ? Object.keys(normaliseEmits(component.emits))
    : []) {
    // camelized so a kebab-case emit still finds a handler passed in props
    const key = toHandlerKey(camelize(name))
    const capture = (...args) => (emitted[name] ||= []).push(args)
    handlers[key] = props[key] ? [capture].concat(props[key]) : capture
  }
  let vm
  const app = createApp({
    render: () => h(component, { ...handlers, ref: (r) => (vm = r) }, slots),
  })
  app.config.globalProperties.__ = globalThis.__
  for (const [name, stub] of Object.entries(stubs)) app.component(name, stub)
  for (const plugin of plugins) app.use(...[].concat(plugin))
  const el = document.createElement('div')
  document.body.appendChild(el)
  try {
    app.mount(el)
  } catch (error) {
    el.remove()
    throw error
  }
  const wrapper = {
    el,
    get vm() {
      return vm
    },
    emitted,
    nextTick,
    unmount() {
      if (!mounted.delete(wrapper)) return
      app.unmount()
      el.remove()
    },
  }
  mounted.add(wrapper)
  return wrapper
}

function normaliseEmits(emits) {
  return Array.isArray(emits)
    ? Object.fromEntries(emits.map((e) => [e, null]))
    : emits
}
