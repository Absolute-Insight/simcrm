import { h, nextTick } from 'vue'

/**
 * Shared stand-ins for component tests that mount the app's modals.
 *
 * main.js registers Dialog, Button and ErrorMessage globally and installs the
 * translation plugin; these reduce them to what a test asserts on. Button keeps
 * frappe-ui's rule that a `loading` button is non-interactive, and exposes
 * `data-loading` so a test can read the busy state.
 *
 *   mount(Modal, { stubs: modalStubs, plugins: [translation] })
 */
export const Dialog = {
  name: 'Dialog',
  props: ['open', 'modelValue', 'options'],
  render() {
    if (!(this.open ?? this.modelValue)) return null
    const close = () => {}
    return h('div', { class: 'stub-Dialog' }, [
      this.$slots['body-content']?.({ close }),
      this.$slots.default?.({ close }),
      this.$slots.actions?.({ close }),
    ])
  },
}

export const Button = {
  name: 'Button',
  inheritAttrs: false,
  props: ['label', 'loading', 'disabled'],
  render() {
    return h(
      'button',
      {
        class: 'stub-Button',
        'data-label': this.label,
        'data-loading': String(!!this.loading),
        disabled: !!(this.disabled || this.loading),
        onClick: (e) => this.$attrs.onClick?.(e),
      },
      this.$slots.default?.() ?? this.label,
    )
  },
}

export const ErrorMessage = {
  name: 'ErrorMessage',
  props: ['message'],
  render() {
    return h('div', { class: 'stub-Error' }, this.message || '')
  },
}

export const modalStubs = { Dialog, Button, ErrorMessage }

export const translation = (app) => {
  app.config.globalProperties.__ = globalThis.__
}

/** Let promise chains and the re-renders they trigger settle. */
export async function flush(rounds = 6) {
  for (let i = 0; i < rounds; i++) {
    await Promise.resolve()
    await nextTick()
  }
}

/** Every mounted component instance under `vnode` whose name is `name`. */
export function findComponents(vnode, name, out = []) {
  if (!vnode) return out
  if (vnode.component) {
    const type = vnode.component.type
    if (type.name === name || type.__name === name) out.push(vnode.component)
    findComponents(vnode.component.subTree, name, out)
  }
  if (Array.isArray(vnode.children)) {
    vnode.children.forEach((c) => findComponents(c, name, out))
  }
  if (vnode.suspense) findComponents(vnode.suspense.activeBranch, name, out)
  return out
}
