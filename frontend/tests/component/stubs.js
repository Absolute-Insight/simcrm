/* eslint-disable vue/one-component-per-file -- a file of stand-ins */
import { defineComponent, h, nextTick } from 'vue'

/*
 * Native stand-ins for frappe-ui form controls whose real versions render
 * through reka-ui popovers (select, combobox) or tiptap (the text editor),
 * which happy-dom cannot drive the way a person does. Each keeps the real
 * control's v-model contract and labels its element with `data-label`, so a
 * test sets a value the way the user would and the component sees the same
 * update:modelValue it gets in the browser.
 *
 *   vi.mock('frappe-ui', async (importOriginal) => {
 *     const { FormControl } = await import('./stubs.js')
 *     return { ...(await importOriginal()), FormControl }
 *   })
 */

function optionsOf(options) {
  return (options || []).map((o) =>
    typeof o === 'string' ? { label: o, value: o } : o,
  )
}

export const FormControl = defineComponent({
  name: 'FormControl',
  inheritAttrs: false,
  props: {
    modelValue: { type: null, default: undefined },
    label: { type: String, default: '' },
    type: { type: String, default: 'text' },
    options: { type: Array, default: () => [] },
    disabled: { type: Boolean, default: false },
  },
  emits: ['update:modelValue', 'change'],
  setup(props, { emit, attrs }) {
    const update = (value) => emit('update:modelValue', value)
    return () => {
      const common = {
        'data-label': props.label || attrs.placeholder,
        name: attrs.name,
        disabled: props.disabled,
      }
      if (props.type === 'select') {
        return h(
          'select',
          {
            ...common,
            value: props.modelValue ?? '',
            onChange: (e) => update(e.target.value),
          },
          optionsOf(props.options).map((o) =>
            h('option', { value: o.value }, o.label),
          ),
        )
      }
      if (props.type === 'checkbox') {
        return h('input', {
          ...common,
          type: 'checkbox',
          checked: Boolean(props.modelValue),
          onChange: (e) => update(e.target.checked),
        })
      }
      return h(props.type === 'textarea' ? 'textarea' : 'input', {
        ...common,
        value: props.modelValue ?? '',
        // the real control passes the native event on to an @input listener
        onInput: (e) => {
          update(e.target.value)
          attrs.onInput?.(e)
        },
      })
    }
  },
})

/** TextInput without its debounce: an input event is the committed value. */
export const TextInput = defineComponent({
  name: 'TextInput',
  inheritAttrs: false,
  props: { modelValue: { type: null, default: undefined } },
  emits: ['update:modelValue'],
  setup(props, { emit, attrs }) {
    return () =>
      h('input', {
        ...attrs,
        'data-label': attrs.placeholder,
        value: props.modelValue ?? '',
        onInput: (e) => emit('update:modelValue', e.target.value),
      })
  },
})

export const Select = defineComponent({
  name: 'SelectStub',
  inheritAttrs: false,
  props: {
    modelValue: { type: null, default: undefined },
    options: { type: Array, default: () => [] },
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () =>
      h(
        'select',
        {
          value: props.modelValue ?? '',
          onChange: (e) => emit('update:modelValue', e.target.value),
        },
        optionsOf(props.options).map((o) =>
          h('option', { value: o.value }, o.label),
        ),
      )
  },
})

/** The rich-text editor as a textarea that reports its HTML on change. */
export const TextEditor = defineComponent({
  name: 'TextEditor',
  inheritAttrs: false,
  props: { content: { type: String, default: '' } },
  emits: ['change'],
  setup(props, { emit }) {
    return () =>
      h('textarea', {
        'data-label': 'editor',
        value: props.content ?? '',
        onInput: (e) => emit('change', e.target.value),
      })
  },
})

/** Fire the events a person's typing fires on a native control. */
export function setValue(element, value) {
  if (element.type === 'checkbox') element.checked = value
  else element.value = value
  element.dispatchEvent(new Event('input'))
  element.dispatchEvent(new Event('change'))
}

export function byLabel(root, label) {
  return root.querySelector(`[data-label="${label}"]`)
}

export function buttonByText(root, text) {
  return [...root.querySelectorAll('button')].find(
    (b) => b.textContent.trim() === text,
  )
}

/** happy-dom under this vitest exposes no localStorage; useBroadcast and the
 *  settings panes write to it. A Map-backed one per test file is enough. */
export function memoryStorage() {
  const items = new Map()
  return {
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    setItem: (key, value) => items.set(key, String(value)),
    removeItem: (key) => items.delete(key),
    clear: () => items.clear(),
  }
}

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
