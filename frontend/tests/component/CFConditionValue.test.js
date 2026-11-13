import { describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { mount } from './mount.js'

// The real CFCondition; the value control is a stub that hands the test the
// `change` listener the row gave it, which is what a native input fires.
const live = vi.hoisted(() => ({ controls: [] }))

vi.mock('frappe-ui', async () => {
  const { defineComponent, h } = await import('vue')
  const leaf = (name) =>
    defineComponent({ name, inheritAttrs: false, setup: () => () => h('i') })
  const control = (name) =>
    defineComponent({
      name,
      inheritAttrs: false,
      setup(_, { attrs }) {
        live.controls.push(attrs)
        return () => h('i')
      },
    })
  return {
    Combobox: leaf('Combobox'),
    Dropdown: leaf('Dropdown'),
    Button: leaf('Button'),
    Rating: leaf('Rating'),
    Dialog: leaf('Dialog'),
    DatePicker: leaf('DatePicker'),
    DateTimePicker: leaf('DateTimePicker'),
    DateRangePicker: leaf('DateRangePicker'),
    FormControl: control('FormControl'),
  }
})
vi.mock('@phosphor-icons/vue', () => ({ PhStack: {}, PhStackMinus: {} }))
vi.mock('@/components/Controls/Link.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      name: 'Link',
      inheritAttrs: false,
      setup(_, { attrs }) {
        live.controls.push(attrs)
        return () => h('i')
      },
    }),
  }
})
vi.mock('@/components/ConditionsFilter/filterableFields', async () => {
  const { reactive } = await import('vue')
  const field = (fieldname, fieldtype, options = '') => ({
    fieldname,
    fieldtype,
    options,
    label: fieldname,
    value: fieldname,
  })
  return {
    filterableFields: reactive({
      data: [
        field('mobile_no', 'Data'),
        field('organization', 'Link', 'CRM Organization'),
        field('priority', 'Select', '1\n2\n3'),
        field('annual_revenue', 'Currency'),
        field('no_of_employees', 'Int'),
      ],
      submit: () => {},
    }),
  }
})
const CFCondition = (
  await import('@/components/ConditionsFilter/CFCondition.vue')
).default

async function change(condition, value) {
  live.controls.length = 0
  const state = reactive(condition)
  const w = mount(CFCondition, { props: { condition: state, level: 0 } })
  await w.nextTick()
  live.controls
    .filter((attrs) => attrs.placeholder === 'Condition')
    .at(-1)
    .onChange(value)
  await w.nextTick()
  return state[2]
}
const typed = (value) => ({ target: { value } })

describe('CFCondition value', () => {
  it('keeps a Data value with a leading zero as typed', async () => {
    expect(await change(['mobile_no', '==', ''], typed('0821234567'))).toBe(
      '0821234567',
    )
  })

  it('an emptied text box stays empty, not 0', async () => {
    expect(await change(['mobile_no', '==', 'abc'], typed(''))).toBe('')
  })

  it('keeps a Link name that looks like a number', async () => {
    expect(await change(['organization', '==', ''], '00123')).toBe('00123')
  })

  it('keeps a Select option that looks like a number', async () => {
    expect(await change(['priority', '==', ''], typed('2'))).toBe('2')
  })

  it('still stores a number for a numeric field', async () => {
    expect(await change(['annual_revenue', '>', ''], typed('1500.50'))).toBe(
      1500.5,
    )
    expect(await change(['no_of_employees', '==', ''], typed('40'))).toBe(40)
  })

  it('an emptied number box is empty, not 0', async () => {
    expect(await change(['no_of_employees', '==', 40], typed(''))).toBe('')
  })

  it('a list or pattern on a numeric field stays text', async () => {
    expect(await change(['no_of_employees', 'in', ''], typed('40'))).toBe('40')
    expect(await change(['no_of_employees', 'like', ''], typed('4'))).toBe('4')
  })
})
