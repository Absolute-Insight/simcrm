import { expect, it, vi } from 'vitest'
import { defineComponent, h, reactive } from 'vue'
import { mount } from './mount.js'

vi.mock('frappe-ui', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    Dialog: defineComponent({
      setup:
        (_, { slots }) =>
        () =>
          h('div', [slots.title?.(), slots.default?.()]),
    }),
    // save_fields_layout fails, as it does on a PermissionError or offline.
    call: () => Promise.reject(new Error('PermissionError')),
    createResource: () =>
      reactive({
        data: [
          {
            name: 'tab',
            sections: [
              {
                name: 's',
                columns: [{ name: 'c', fields: [{ fieldname: 'qty' }] }],
              },
            ],
          },
        ],
        reload() {},
      }),
  }
})
vi.mock('@/components/FieldLayout/FieldLayout.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/FieldLayoutEditor.vue', () => ({
  default: { render: () => null },
}))
const reported = []
vi.mock('@/utils/reportActionError', () => ({
  reportActionError: (_error, message) => reported.push(message),
}))

const Modal = (await import('@/components/Controls/GridRowFieldsModal.vue'))
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

it('a failed layout save leaves Save ready for a retry', async () => {
  const w = mount(Modal, {
    props: {
      modelValue: true,
      doctype: 'CRM Products',
      parentDoctype: 'CRM Deal',
    },
    stubs: { Button },
    plugins: [
      { install: (app) => (app.config.globalProperties.__ = globalThis.__) },
    ],
  })
  await w.nextTick()
  w.el.querySelector('button[data-label="Save"]').click()
  await new Promise((resolve) => setTimeout(resolve, 0))
  await w.nextTick()
  expect(reported).toEqual(['Could not save the layout.'])
  expect(w.el.querySelector('button[data-label="Save"]').dataset.loading).toBe(
    'false',
  )
  w.unmount()
})
