import { defineComponent, h, reactive } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// The row comboboxes, in render order, so a test can pick one by the field it shows.
const comboboxes = []

vi.mock('frappe-ui', () => ({
  Combobox: defineComponent({
    props: ['options', 'modelValue', 'placeholder'],
    emits: ['update:selectedOption'],
    setup(props, { emit, slots }) {
      comboboxes.push({
        props,
        select: (o) => emit('update:selectedOption', o),
      })
      return () =>
        h(
          'div',
          slots.trigger?.({
            open: false,
            setOpen() {},
            displayValue: props.modelValue,
          }),
        )
    },
  }),
  // Open, so the sort rows render.
  Popover: defineComponent({
    setup:
      (_, { slots }) =>
      () =>
        h('div', [
          slots.trigger?.({ open: true }),
          slots.default?.({ close() {} }),
        ]),
  }),
  createResource: () =>
    reactive({
      data: [
        { fieldname: 'probability', label: 'Probability' },
        { fieldname: 'deal_value', label: 'Deal Value' },
        { fieldname: 'expected_closure_date', label: 'Expected Closure Date' },
      ],
      fetch() {},
    }),
}))
vi.mock('@vueuse/integrations/useSortable', () => ({
  useSortable: () => ({ start() {}, stop() {} }),
}))

const { default: SortBy } = await import('@/components/SortBy.vue')

const Button = defineComponent({ setup: () => () => h('button') })

describe('SortBy', () => {
  it('changing the field of a sort row keeps the row where it was', async () => {
    const list = reactive({
      data: [{}],
      params: { order_by: 'probability desc, deal_value asc' },
    })
    const w = mount(SortBy, {
      props: { doctype: 'CRM Deal', modelValue: list },
      stubs: { Button },
    })
    await w.nextTick()

    comboboxes
      .find((c) => c.props.modelValue === 'probability')
      .select({ fieldname: 'expected_closure_date' })
    await w.nextTick()

    // Primary sort replaced in place, its direction kept; the secondary stays second.
    expect(w.emitted.update.at(-1)).toEqual([
      'expected_closure_date desc, deal_value asc',
    ])
  })
})
