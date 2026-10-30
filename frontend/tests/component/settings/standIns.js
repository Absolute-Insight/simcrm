/* eslint-disable vue/one-component-per-file, vue/require-default-prop -- stand-ins for frappe-ui controls */
/**
 * frappe-ui for the Settings pane tests: its real resource layer, wired to an
 * in-memory backend through frappe-ui's own `resourceFetcher` hook, beside
 * stand-ins for the form controls. What these tests check is what a pane sends
 * and when it reloads, so the resources stay real; the controls are swapped
 * because frappe-ui's own are reka-ui listboxes and portals that a test cannot
 * drive the way a person does. Every stand-in renders a native element named
 * by `data-label`, and a FormControl of type "select" is a real <select>.
 *
 *   const backend = vi.hoisted(() => ({ handlers: {}, log: [], toasts: [] }))
 *   vi.mock('frappe-ui', async (importOriginal) =>
 *     (await import('./standIns.js')).frappeUi(importOriginal, backend))
 *
 * A handler is keyed by method path and answers with what frappeRequest would
 * resolve to: the `message`, already unwrapped. A handler that returns a
 * promise holds the request until the test settles it.
 */
import { defineComponent, h } from 'vue'

export async function frappeUi(importOriginal, backend, overrides = {}) {
  const actual = await importOriginal()
  const dispatch = async (url, params = {}) => {
    backend.log.push({ url, params: JSON.parse(JSON.stringify(params)) })
    const handler = backend.handlers[url]
    if (!handler) throw new Error(`no fake handler for ${url}`)
    return handler(params)
  }
  actual.setConfig('resourceFetcher', (opts) => dispatch(opts.url, opts.params))
  actual.setConfig('fallbackErrorHandler', () => {})
  const toast = Object.fromEntries(
    ['success', 'error', 'info', 'warning'].map((kind) => [
      kind,
      (message) => backend.toasts?.push([kind, message]),
    ]),
  )
  return {
    ...actual,
    call: dispatch,
    toast,
    Badge,
    Button,
    Dialog,
    ErrorMessage,
    FormControl,
    Switch,
    Tooltip,
    ...overrides,
  }
}

export function failure(message) {
  const error = new Error(message)
  error.messages = [message]
  return error
}

const settled = () => new Promise((resolve) => setTimeout(resolve, 0))
export async function flush(rounds = 6) {
  for (let i = 0; i < rounds; i++) await settled()
}

export const field = (el, label) => el.querySelector(`[data-label="${label}"]`)

/** Type into an input, or pick an option of a select, the way a person does. */
export async function enter(el, label, value) {
  const control = field(el, label)
  control.value = value
  control.dispatchEvent(
    new Event(control.tagName === 'SELECT' ? 'change' : 'input'),
  )
  await flush()
}

const Badge = defineComponent({
  props: { label: [String, Number] },
  setup:
    (props, { slots }) =>
    () =>
      h('span', { 'data-stub': 'Badge' }, slots.default?.() ?? props.label),
})

const Button = defineComponent({
  props: { label: String, loading: Boolean, disabled: Boolean },
  emits: ['click'],
  setup:
    (props, { emit, attrs, slots }) =>
    () =>
      h(
        'button',
        {
          'data-label': props.label ?? attrs['aria-label'],
          disabled: props.disabled || props.loading,
          onClick: (e) => emit('click', e),
        },
        slots.default?.() || props.label,
      ),
})

const FormControl = defineComponent({
  inheritAttrs: false,
  props: { modelValue: null, label: String, type: String, options: Array },
  emits: ['update:modelValue', 'blur'],
  setup:
    (props, { emit }) =>
    () =>
      props.type === 'select'
        ? h(
            'select',
            {
              'data-label': props.label,
              value: props.modelValue ?? '',
              onChange: (e) => emit('update:modelValue', e.target.value),
            },
            (props.options || []).map((o) =>
              typeof o === 'string'
                ? h('option', { value: o }, o)
                : h('option', { value: o.value }, o.label),
            ),
          )
        : h('input', {
            'data-label': props.label,
            value: props.modelValue ?? '',
            onInput: (e) => emit('update:modelValue', e.target.value),
            onBlur: (e) => emit('blur', e),
          }),
})

const Dialog = defineComponent({
  props: { modelValue: Boolean },
  emits: ['update:modelValue'],
  setup:
    (props, { slots, emit }) =>
    () => {
      const close = () => emit('update:modelValue', false)
      return props.modelValue
        ? h('div', { 'data-stub': 'Dialog' }, [
            slots.default?.({ close }),
            slots.actions?.({ close }),
          ])
        : null
    },
})

const ErrorMessage = defineComponent({
  props: { message: [String, Error, Object] },
  setup: (props) => () =>
    h(
      'p',
      { 'data-stub': 'ErrorMessage' },
      props.message?.message ?? props.message ?? '',
    ),
})

const Switch = defineComponent({
  props: { modelValue: { type: Boolean, default: false }, label: String },
  emits: ['update:modelValue'],
  setup:
    (props, { emit }) =>
    () =>
      h('button', {
        role: 'switch',
        'data-label': props.label,
        'aria-checked': String(props.modelValue),
        onClick: () => emit('update:modelValue', !props.modelValue),
      }),
})

const Tooltip = defineComponent({
  setup:
    (_, { slots }) =>
    () =>
      slots.default?.(),
})
