import { defineComponent, h, reactive } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

const passThrough = (name) =>
  defineComponent({
    name,
    setup:
      (_, { slots }) =>
      () =>
        h('div', slots.default?.()),
  })

// The real FormControl (and the TextInput it forwards `debounce` to); the
// Popover is held open and the Combobox is not under test.
vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  Combobox: passThrough('Combobox'),
  Popover: defineComponent({
    setup:
      (_, { slots }) =>
      () =>
        h('div', [slots.trigger?.({}), slots.default?.({ close() {} })]),
  }),
}))
vi.mock('vuedraggable', () => ({
  default: defineComponent({
    props: { list: Array },
    setup:
      (props, { slots }) =>
      () =>
        h(
          'div',
          props.list.map((element) => slots.item({ element })),
        ),
  }),
}))
vi.mock('@/utils', () => ({ isTouchScreenDevice: () => false }))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({ getFields: () => [] }) }))

const { FormControl } = await import('frappe-ui')
const { default: ColumnSettings } = await import(
  '@/components/ColumnSettings.vue'
)

const Button = defineComponent({
  props: { label: { type: String, default: '' } },
  setup:
    (props, { attrs, slots }) =>
    () =>
      h('button', { onClick: attrs.onClick }, [props.label, slots.icon?.()]),
})

describe('ColumnSettings', () => {
  it('Update applies a width typed just before it', async () => {
    const list = reactive({
      data: {
        columns: [
          { label: 'Organization', key: 'organization', width: '10rem' },
        ],
        rows: ['name', 'organization'],
        is_default: false,
      },
    })
    const w = mount(ColumnSettings, {
      props: { modelValue: list, doctype: 'CRM Deal' },
      stubs: { Button, FormControl },
    })
    await w.nextTick()

    // the pencil is the first unlabelled button on the column's row
    ;[...w.el.querySelectorAll('button')]
      .find((b) => !b.textContent.trim())
      .click()
    await w.nextTick()
    const inputs = w.el.querySelectorAll('input')
    const width = inputs[inputs.length - 1]
    expect(width.value).toBe('10rem')

    width.value = '18rem'
    width.dispatchEvent(new Event('input', { bubbles: true }))
    // and clicks Update straight away
    ;[...w.el.querySelectorAll('button')]
      .find((b) => b.textContent === 'Update')
      .click()
    await w.nextTick()

    expect(w.emitted.update.at(-1)[0].columns[0].width).toBe('18rem')
    expect(list.data.columns[0].width).toBe('18rem')
  })
  /* Reset Changes handed over the pre-edit isDefault, which on a list that had
     never been customised is true: Reset to Default then hid itself, and the
     parent read it as "go back to the defaults" and dropped the columns. */
  it('Reset Changes restores the columns and keeps Reset to Default', async () => {
    const list = reactive({
      data: {
        columns: [
          { label: 'Organization', key: 'organization', width: '10rem' },
          { label: 'Status', key: 'status', width: '10rem' },
        ],
        rows: ['name', 'organization', 'status'],
        is_default: true,
      },
    })
    const original = JSON.parse(JSON.stringify(list.data))
    const w = mount(ColumnSettings, {
      props: { modelValue: list, doctype: 'CRM Deal' },
      stubs: { Button, FormControl },
    })
    await w.nextTick()
    const button = (label) =>
      [...w.el.querySelectorAll('button')].find(
        (b) => b.textContent === label,
      )

    // a column removed: the x beside the pencil on its row
    ;[...w.el.querySelectorAll('button')]
      .filter((b) => !b.textContent.trim())[1]
      .click()
    await w.nextTick()
    expect(list.data.columns).toHaveLength(1)

    button('Reset Changes').click()
    await w.nextTick()
    const update = w.emitted.update.at(-1)[0]
    expect(update.columns).toEqual(original.columns)
    expect(update.rows).toEqual(original.rows)
    expect(update.isDefault).toBe(false)
    expect(update.reset).toBe(true)

    await new Promise((resolve) => setTimeout(resolve, 120))
    await w.nextTick()
    expect(button('Reset to Default')).toBeTruthy()
    expect(button('Reset Changes')).toBeFalsy()
  })
})
