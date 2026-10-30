import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from './mount.js'

const passThrough = (name) =>
  defineComponent({
    name,
    setup:
      (_, { slots }) =>
      () =>
        h('div', slots.default?.()),
  })

vi.mock('frappe-ui', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    Dialog: defineComponent({
      setup:
        (_, { slots }) =>
        () =>
          h('div', [slots.title?.(), slots.default?.(), slots.actions?.()]),
    }),
    Combobox: defineComponent({ render: () => h('div') }),
    ErrorMessage: defineComponent({
      props: { message: String },
      setup: (p) => () => h('p', { class: 'error' }, p.message),
    }),
  }
})
vi.mock('vuedraggable', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      props: { list: { type: Array, default: () => [] } },
      setup:
        (props, { slots }) =>
        () =>
          h(
            'div',
            props.list.map((element) => slots.item({ element })),
          ),
    }),
  }
})

let gridView = []
const metaFields = [
  {
    fieldname: 'product_code',
    fieldtype: 'Link',
    label: 'Product',
    in_list_view: 1,
  },
  { fieldname: 'qty', fieldtype: 'Float', label: 'Quantity', in_list_view: 1 },
]
const saved = []
vi.mock('@/stores/meta', () => ({
  getMeta: () => ({
    getFields: () => metaFields,
    getGridViewSettings: () => gridView,
    saveUserSettings: (_parent, _key, value, callback) => {
      saved.push(value)
      callback?.()
    },
  }),
}))

const Modal = (await import('@/components/Controls/GridFieldsEditorModal.vue'))
  .default

const Button = defineComponent({
  props: { label: String, loading: Boolean },
  setup:
    (p, { attrs }) =>
    () =>
      h('button', {
        'data-label': p.label,
        'data-loading': String(p.loading),
        onClick: attrs.onClick,
      }),
})

function open() {
  const errors = []
  const w = mount(Modal, {
    props: {
      modelValue: true,
      doctype: 'CRM Products',
      parentDoctype: 'CRM Deal',
    },
    stubs: { Button, TextInput: passThrough('TextInput') },
    plugins: [
      {
        install(app) {
          app.config.globalProperties.__ = globalThis.__
          app.config.errorHandler = (e) => errors.push(String(e))
        },
      },
    ],
  })
  return { ...w, errors }
}

describe('GridFieldsEditorModal', () => {
  it('opens when a saved column refers to a field that is gone', async () => {
    gridView = [
      { fieldname: 'qty', columns: 3 },
      { fieldname: 'old_discount', columns: 1 },
    ]
    const w = open()
    await w.nextTick()
    expect(w.errors).toEqual([])
    expect(w.el.textContent).toContain('Quantity')
    // Opening the editor must not write the saved width into cached meta.
    expect(metaFields.find((f) => f.fieldname === 'qty').columns).toBe(
      undefined,
    )
    w.unmount()
  })

  it('Save works again after the "At least one field" error', async () => {
    gridView = [{ fieldname: 'qty', columns: 2 }]
    saved.length = 0
    const w = open()
    await w.nextTick()
    const removeButtons = () =>
      [...w.el.querySelectorAll('button')].filter((b) => !b.dataset.label)
    removeButtons()[0].click()
    await w.nextTick()
    const save = () => w.el.querySelector('button[data-label="Save"]')
    save().click()
    await w.nextTick()
    expect(w.el.querySelector('.error').textContent).toBe(
      'At least one field is required',
    )
    expect(save().dataset.loading).toBe('false')
    expect(saved).toEqual([])
    w.unmount()
  })
})
