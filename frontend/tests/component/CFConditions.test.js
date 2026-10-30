import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { mount } from './mount.js'

// The real CFConditions and CFCondition; frappe-ui's leaf controls are stubs
// that record their live instances so a test can drive them.
const live = vi.hoisted(() => ({ combobox: [], dropdown: [], picker: [] }))

vi.mock('frappe-ui', async () => {
  const { defineComponent, h, onUnmounted } = await import('vue')
  const track = (kind, entry) => {
    live[kind].push(entry)
    onUnmounted(() => live[kind].splice(live[kind].indexOf(entry), 1))
  }
  const leaf = (name) =>
    defineComponent({
      name,
      inheritAttrs: false,
      setup: () => () => h('i'),
    })
  const picker = (name) =>
    defineComponent({
      name,
      inheritAttrs: false,
      props: { modelValue: null },
      emits: ['update:modelValue', 'change'],
      setup(props, { emit }) {
        track('picker', { name, props, emit })
        return () => h('i')
      },
    })
  return {
    Combobox: defineComponent({
      inheritAttrs: false,
      props: { modelValue: null },
      setup(props, { attrs }) {
        track('combobox', { props, attrs })
        return () => h('span', { class: 'field' }, props.modelValue ?? '')
      },
    }),
    Dropdown: defineComponent({
      props: { options: null },
      setup(props, { slots }) {
        track('dropdown', { props })
        return () => h('div', slots.default?.({ open: false }))
      },
    }),
    Button: leaf('Button'),
    FormControl: leaf('FormControl'),
    Rating: leaf('Rating'),
    Dialog: leaf('Dialog'),
    DatePicker: picker('DatePicker'),
    DateTimePicker: picker('DateTimePicker'),
    DateRangePicker: picker('DateRangePicker'),
  }
})
vi.mock('@phosphor-icons/vue', () => ({ PhStack: {}, PhStackMinus: {} }))
vi.mock('@/components/Controls/Link.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/ConditionsFilter/filterableFields', async () => {
  const { reactive } = await import('vue')
  const field = (fieldname, fieldtype) => ({
    fieldname,
    fieldtype,
    label: fieldname,
    value: fieldname,
  })
  return {
    filterableFields: reactive({
      data: [
        field('first_name', 'Data'),
        field('email', 'Data'),
        field('last_name', 'Data'),
        field('creation', 'Datetime'),
      ],
      submit: () => {},
    }),
  }
})

const CFConditions = (
  await import('@/components/ConditionsFilter/CFConditions.vue')
).default

const translate = {
  install: (app) => (app.config.globalProperties.__ = globalThis.__),
}
const plain = (v) => JSON.parse(JSON.stringify(v))
const shownFields = (el) =>
  [...el.querySelectorAll('.field')].map((n) => n.textContent)
const pick = (dropdown, label) =>
  dropdown.props.options.find((o) => o.label === label).onClick()

function open(conditions) {
  const errors = []
  const w = mount(CFConditions, {
    props: { conditions, level: 0, doctype: 'CRM Lead' },
    plugins: [
      translate,
      { install: (app) => (app.config.errorHandler = (e) => errors.push(e)) },
    ],
  })
  return { ...w, errors }
}

beforeEach(() => {
  for (const kind of Object.keys(live)) live[kind].length = 0
})

describe('CFConditions rows follow the data', () => {
  it('Remove on the first of two conditions removes that row', async () => {
    const conditions = reactive([
      ['first_name', '==', 'Alice'],
      'and',
      ['email', '==', 'bob@x.co'],
    ])
    const w = open(conditions)
    await w.nextTick()
    expect(shownFields(w.el)).toEqual(['first_name', 'email'])

    pick(live.dropdown[0], 'Remove')
    await w.nextTick()
    expect(plain(conditions)).toEqual([['email', '==', 'bob@x.co']])
    expect(shownFields(w.el)).toEqual(['email'])

    // Editing the row left on screen edits the condition that is saved.
    const onPick = Object.entries(live.combobox[0].attrs).find(([k]) =>
      /^onUpdate:selected/.test(k),
    )[1]
    onPick({ fieldname: 'last_name' })
    await w.nextTick()
    expect(plain(conditions)[0][0]).toBe('last_name')
    w.unmount()
  })

  it('Turn into a Group shows the condition inside the new group', async () => {
    const conditions = reactive([['first_name', '==', 'Alice']])
    const w = open(conditions)
    await w.nextTick()
    pick(live.dropdown[0], 'Turn into a Group')
    await w.nextTick()
    expect(plain(conditions)).toEqual([[['first_name', '==', 'Alice']]])
    expect(shownFields(w.el)).toEqual(['first_name'])

    const groupMenu = live.dropdown.find((d) =>
      d.props.options.some((o) => o.label === 'Add Condition Group'),
    )
    pick(groupMenu, 'Add Condition')
    await w.nextTick()
    expect(plain(conditions)).toEqual([
      [['first_name', '==', 'Alice'], 'and', ['', '', '']],
    ])
    w.unmount()
  })
})
