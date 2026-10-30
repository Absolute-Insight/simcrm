import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, provide, reactive } from 'vue'
import { mount } from './mount.js'

// Grid.vue mounted against the real useDocument() row hooks and the real form
// script evaluator; only the leaf controls, the record resource and the
// script fetch are stubbed.

const stub = (name, tag = 'div') =>
  defineComponent({
    name,
    inheritAttrs: false,
    setup:
      (_, { slots, attrs }) =>
      () =>
        h(
          tag,
          {
            'data-stub': name,
            onClick: attrs.onClick,
            onChange: attrs.onChange,
          },
          slots.default?.(),
        ),
  })

const records = {}
// getScript() fetches a doctype's scripts once per session, so every test
// shares this one. rate() has the shape of the shipped Product Details
// script: it finds its row through getRow(), i.e. by this.currentRowIdx.
const SCRIPT = `
class CRMDeal {
  update_total() {
    this.doc.total = this.doc.products.reduce((t, d) => t + (d.amount || 0), 0)
  }
}
class CRMProducts {
  rate() {
    let row = this.doc.getRow('products')
    row.amount = row.qty * row.rate
    this.doc.trigger('update_total')
  }
  products_remove() {
    window.removeHookSaw.push({
      selectedRows: [...this.selectedRows],
      currentRowIdx: this.currentRowIdx,
      rows: this.rows.map((r) => r.name),
    })
  }
}`
vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  createDocumentResource: ({ name }) =>
    (records[name] ||= reactive({
      doc: { name, doctype: 'CRM Deal', products: [] },
      save: { submit: async () => {} },
    })),
  createResource: () => reactive({ data: null, reload() {}, fetch() {} }),
  createListResource: (o) => ({
    loading: false,
    list: { promise: Promise.resolve() },
    fetch: () => o.onSuccess([{ name: 'Deal Script', script: SCRIPT }]),
  }),
  call: async () => null,
  Checkbox: stub('Checkbox', 'input'),
  FormControl: stub('FormControl'),
  TimePicker: stub('TimePicker'),
  DateTimePicker: stub('DateTimePicker'),
  DatePicker: stub('DatePicker'),
  Tooltip: stub('Tooltip'),
  Combobox: stub('Combobox'),
}))
vi.mock('vuedraggable', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      props: { modelValue: { type: Array, default: () => [] } },
      setup:
        (p, { slots }) =>
        () =>
          h(
            'div',
            p.modelValue.map((element, index) =>
              slots.item({ element, index }),
            ),
          ),
    }),
  }
})
const linkAttrs = []
vi.mock('@/components/Controls/Link.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      inheritAttrs: false,
      setup(_, { attrs }) {
        linkAttrs.push(attrs)
        return () => h('div', { 'data-stub': 'Link' })
      },
    }),
  }
})
vi.mock('@/components/Controls/FormattedInput.vue', () => ({
  default: stub('FormattedInput', 'input'),
}))
vi.mock('@/components/Controls/GridFieldsEditorModal.vue', () => ({
  default: stub('GridFieldsEditorModal'),
}))
vi.mock('@/components/Controls/GridRowFieldsModal.vue', () => ({
  default: stub('GridRowFieldsModal'),
}))
vi.mock('@/components/Controls/GridRowModal.vue', () => ({
  default: stub('GridRowModal'),
}))
vi.mock('@/components/Controls/TextEditorControl.vue', () => ({
  default: stub('TextEditorControl'),
}))
const created = []
vi.mock('@/composables/document', () => ({
  createDocument: (...args) => created.push(args),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ users: { data: {} }, getUser: () => ({}) }),
}))
const fields = [
  {
    fieldname: 'product_code',
    fieldtype: 'Link',
    options: 'CRM Product',
    label: 'Product',
    in_list_view: 1,
  },
  { fieldname: 'qty', fieldtype: 'Float', label: 'Qty', default: '1' },
  { fieldname: 'rate', fieldtype: 'Currency', label: 'Rate', in_list_view: 1 },
  { fieldname: 'amount', fieldtype: 'Currency', label: 'Amount' },
]
let gridView = []
vi.mock('@/stores/meta', () => ({
  getMeta: () => ({
    doctypesMeta: {},
    getFields: () => fields,
    getGridViewSettings: () => gridView,
    getGridSettings: () => ({ editable_grid: 1 }),
    getFloatWithPrecision: () => '',
    getCurrencyWithPrecision: () => '',
    getFormattedCurrency: () => '',
  }),
}))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ makeCall: () => {}, $dialog: () => {}, $socket: null }),
}))
vi.mock('@/composables/useAttachments', () => ({
  useAttachments: () => ({
    trackOldFile: () => {},
    processPendingDeletions: () => {},
  }),
}))
vi.mock('@/router', () => ({ default: {} }))

const { useDocument } = await import('@/data/document')
const Grid = (await import('@/components/Controls/Grid.vue')).default

const Button = defineComponent({
  props: { label: String },
  setup:
    (p, { attrs }) =>
    () =>
      h('button', { 'data-label': p.label, onClick: attrs.onClick }, p.label),
})

// main.js registers __ app-wide for templates.
const translate = {
  install: (app) => (app.config.globalProperties.__ = globalThis.__),
}

const row = (name, idx, rate) => ({
  name,
  idx,
  doctype: 'CRM Products',
  parentfield: 'products',
  parenttype: 'CRM Deal',
  qty: 1,
  rate,
  amount: rate,
})

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

let docCount = 0
async function mountGrid(products) {
  const name = `D-${++docCount}`
  const doc = useDocument('CRM Deal', name)
  const record = records[name]
  record.doc.products = products
  await doc.setupFormScript()
  const Host = defineComponent({
    setup() {
      provide('triggerOnChange', doc.triggerOnChange)
      provide('triggerOnRowAdd', doc.triggerOnRowAdd)
      provide('triggerOnRowRemove', doc.triggerOnRowRemove)
      return () =>
        h(Grid, {
          modelValue: record.doc.products,
          'onUpdate:modelValue': (v) => (record.doc.products = v),
          doctype: 'CRM Products',
          parentDoctype: 'CRM Deal',
          parentFieldname: 'products',
        })
    },
  })
  const w = mount(Host, { stubs: { Button }, plugins: [translate] })
  await nextTick()
  return { ...w, record }
}

async function deleteRow(el, position) {
  el.querySelectorAll('.grid-row [data-stub="Checkbox"]')[position].click()
  await nextTick()
  el.querySelector('button[data-label="Delete"]').click()
  await settle()
  await nextTick()
}

async function addRow(el) {
  el.querySelector('button[data-label="Add Row"]').click()
  await settle()
  await nextTick()
}

beforeEach(() => (window.removeHookSaw = []))

describe('Grid rows', () => {
  it('renumbers after a delete, so an added row gets its own idx', async () => {
    const { el, record, unmount } = await mountGrid([
      row('r1', 1, 100),
      row('r2', 2, 200),
      row('r3', 3, 300),
    ])
    await deleteRow(el, 1)
    await addRow(el)
    expect(record.doc.products.map((r) => r.idx)).toEqual([1, 2, 3])

    // The products script prices the row that was edited, not the old row 3
    // that used to share its idx, and the deal total includes it.
    const rates = el.querySelectorAll(
      '.grid-row input[data-stub="FormattedInput"]',
    )
    const rate = rates[rates.length - 1]
    rate.value = '200'
    rate.dispatchEvent(new Event('change'))
    await settle()
    expect(record.doc.products.map((r) => r.amount)).toEqual([100, 300, 200])
    expect(record.doc.total).toBe(600)
    unmount()
  })

  it('gives an added row an idx past the highest one present', async () => {
    const { el, record, unmount } = await mountGrid([
      row('r1', 1, 100),
      row('r3', 3, 300),
    ])
    await addRow(el)
    expect(record.doc.products.map((r) => r.idx)).toEqual([1, 3, 4])
    unmount()
  })
})

describe('Grid [parentfield]_remove hook', () => {
  it('receives the removed names, their idx and the remaining rows', async () => {
    const seen = (window.removeHookSaw = [])
    const { el, unmount } = await mountGrid([
      row('r1', 1, 100),
      row('r2', 2, 200),
      row('r3', 3, 300),
    ])
    await deleteRow(el, 1)
    expect(seen).toEqual([
      { selectedRows: ['r2'], currentRowIdx: 2, rows: ['r1', 'r3'] },
    ])
    unmount()
  })

  it('still fires when every row is deleted', async () => {
    const seen = (window.removeHookSaw = [])
    const { el, record, unmount } = await mountGrid([
      row('r1', 1, 100),
      row('r2', 2, 200),
    ])
    for (const box of el.querySelectorAll('.grid-row [data-stub="Checkbox"]'))
      box.click()
    await nextTick()
    el.querySelector('button[data-label="Delete"]').click()
    await settle()
    expect(record.doc.products).toEqual([])
    expect(seen).toEqual([{ selectedRows: ['r1', 'r2'], rows: [] }])
    unmount()
  })
})
