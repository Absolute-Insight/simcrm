import { h, nextTick, reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// The record cache (one reactive entry per docname, as data/document.js
// keeps), the users store, the filters each Link is handed, and a count of
// depends_on evaluations -- three per parsed field.
const S = vi.hoisted(() => ({
  docs: {},
  users: null,
  linkFilters: {},
  evals: 0,
}))

const { stub } = vi.hoisted(() => ({
  stub: (name, tag = 'div') => ({
    name,
    inheritAttrs: false,
    setup:
      (_, { slots }) =>
      () =>
        h(tag, { 'data-stub': name }, slots.default?.()),
  }),
}))

vi.mock('frappe-ui', () => ({
  Checkbox: stub('Checkbox'),
  DatePicker: stub('DatePicker'),
  DateTimePicker: stub('DateTimePicker'),
  Duration: stub('Duration'),
  Password: stub('Password'),
  Rating: stub('Rating'),
  Select: stub('Select'),
  Textarea: stub('Textarea'),
  TextInput: stub('TextInput', 'input'),
  TimePicker: stub('TimePicker'),
  Tooltip: stub('Tooltip'),
}))
vi.mock('@/components/Controls/FormattedInput.vue', () => ({
  default: stub('FormattedInput'),
}))
vi.mock('@/components/Controls/AttachControl.vue', () => ({
  default: stub('AttachControl'),
}))
vi.mock('@/components/Controls/HtmlControl.vue', () => ({
  default: stub('HtmlControl'),
}))
vi.mock('@/components/Controls/GeolocationControl.vue', () => ({
  default: stub('GeolocationControl'),
}))
vi.mock('@/components/Controls/TextEditorControl.vue', () => ({
  default: stub('TextEditorControl'),
}))
vi.mock('@/components/Controls/ButtonControl.vue', () => ({
  default: stub('ButtonControl'),
  getButtonTheme: () => 'gray',
  getButtonVariant: () => 'subtle',
}))
vi.mock('@/components/PrimaryDropdown.vue', () => ({
  default: stub('PrimaryDropdown'),
}))
vi.mock('@/components/Icons/ArrowUpRightIcon.vue', () => ({
  default: stub('ArrowUpRightIcon'),
}))
vi.mock('@/components/Icons/EditIcon.vue', () => ({
  default: stub('EditIcon'),
}))
vi.mock('@/components/UserAvatar.vue', () => ({ default: stub('UserAvatar') }))
vi.mock('@/components/Modals/SidePanelModal.vue', () => ({
  default: stub('SidePanelModal'),
}))
// These two render their default slot, which is where the fields are.
vi.mock('@/components/CollapsibleSection.vue', () => ({
  default: stub('CollapsibleSection'),
}))
vi.mock('@/components/FadedScrollableDiv.vue', () => ({
  default: stub('FadedScrollableDiv'),
}))
vi.mock('@/components/Controls/Link.vue', () => ({
  default: {
    props: { doctype: String, filters: { type: Object, default: null } },
    setup: (props) => () => {
      S.linkFilters[props.doctype] = props.filters
      return null
    },
  },
}))
vi.mock('@/stores/meta', () => ({
  getMeta: () => ({
    getFormattedPercent: () => '',
    getFormattedFloat: () => '',
    getFormattedCurrency: () => '',
  }),
}))
vi.mock('@/stores/users', async () => {
  const { reactive } = await import('vue')
  S.users = reactive({ data: { crmUsers: [] } })
  return {
    usersStore: () => ({
      users: S.users,
      isManager: () => false,
      getUser: () => ({}),
    }),
  }
})
vi.mock('@/composables/settings', async () => {
  const { ref } = await import('vue')
  return { isMobileView: ref(false) }
})
vi.mock('@/composables/document', () => ({ createDocument: () => {} }))
vi.mock('@/utils', async () => {
  const { evaluateDependsOnValue } = await vi.importActual(
    '@/utils/expressions',
  )
  return {
    getFormat: () => '',
    evaluateDependsOnValue: (...args) => {
      S.evals += 1
      return evaluateDependsOnValue(...args)
    },
    isNull: (v) => v === undefined || v === null || String(v).trim() === '',
    interpolateTemplate: (t) => t,
  }
})
vi.mock('@/data/document', () => ({
  useDocument: (doctype, name) => ({
    document: S.docs[name],
    triggerOnChange: async () => {},
    triggerButton: async () => {},
  }),
}))

const { default: SidePanelLayout } = await import(
  '@/components/SidePanelLayout.vue'
)

// What get_sidepanel_sections returns, held by one cached resource.
function layout() {
  return reactive([
    {
      name: 'details_section',
      label: 'Details',
      opened: true,
      columns: [
        {
          name: 'column_1',
          fields: [
            { fieldname: 'status', fieldtype: 'Data', label: 'Status' },
            {
              fieldname: 'po_number',
              fieldtype: 'Data',
              label: 'PO Number',
              read_only: 0,
              read_only_depends_on: "eval:doc.status=='Won'",
            },
            { fieldname: 'territory', fieldtype: 'Data', label: 'Territory' },
          ],
        },
      ],
    },
  ])
}

function record(name, doc) {
  S.docs[name] = reactive({ doc: { name, ...doc }, fieldPropertyOverrides: {} })
  return S.docs[name]
}

function open(sections, docname, extra = {}) {
  return mount(SidePanelLayout, {
    props: { sections, doctype: 'CRM Deal', docname, ...extra },
    stubs: { Button: stub('Button') },
  })
}

// Fields rendered as an editable input rather than read-only text.
const editable = (w) =>
  w.el.querySelectorAll('input[data-stub="TextInput"]').length

describe('SidePanelLayout', () => {
  beforeEach(() => {
    for (const key of Object.keys(S.docs)) delete S.docs[key]
    S.users.data = { crmUsers: [] }
  })

  it('makes a field editable again once its read_only_depends_on clears', async () => {
    const deal = record('A', { status: 'Open', po_number: 'PO-1' })
    const sections = layout()
    const w = open(sections, 'A')
    await nextTick()
    expect(editable(w)).toBe(3)

    deal.doc.status = 'Won'
    await nextTick()
    expect(editable(w)).toBe(2)

    deal.doc.status = 'Open'
    await nextTick()
    expect(editable(w)).toBe(3)
    expect(sections[0].columns[0].fields[1].read_only).toBe(0)
  })

  it('shows a field again when a script removes its hidden override', async () => {
    const deal = record('B', { status: 'Open', territory: 'Gauteng' })
    const w = open(layout(), 'B')
    await nextTick()

    deal.fieldPropertyOverrides.territory = { hidden: true }
    await nextTick()
    expect(editable(w)).toBe(2)

    delete deal.fieldPropertyOverrides.territory
    await nextTick()
    expect(editable(w)).toBe(3)
  })

  it('leaves the layout it previews unchanged', async () => {
    const sections = layout()
    sections[0].columns[0].fields.push(
      {
        fieldname: 'stage',
        fieldtype: 'Select',
        label: 'Stage',
        options: 'A\nB',
      },
      {
        fieldname: 'deal_owner',
        fieldtype: 'Link',
        label: 'Owner',
        options: 'User',
      },
    )
    // SidePanelModal's "Not Saved" compares this layout with the saved one.
    const before = JSON.stringify(sections)
    open(sections, '', { preview: true })
    await nextTick()
    expect(JSON.stringify(sections)).toBe(before)
  })

  it('gives a User link the CRM users once the users store loads', async () => {
    S.users.data = null // the page rendered before crm-users resolved
    record('E', { status: 'Open', deal_owner: '' })
    const sections = layout()
    sections[0].columns[0].fields.push({
      fieldname: 'deal_owner',
      fieldtype: 'Link',
      label: 'Deal Owner',
      options: 'User',
    })
    open(sections, 'E')
    await nextTick()

    S.users.data = { crmUsers: [{ name: 'rep@mbp.example' }] }
    await nextTick()
    await nextTick()
    expect(S.linkFilters.User?.name).toEqual(['in', ['rep@mbp.example']])
  })

  it('parses the layout once on mount and once per change', async () => {
    const deal = record('P', { status: 'Open' })
    const sections = reactive(
      Array.from({ length: 5 }, (_, si) => ({
        name: 's' + si,
        label: 'S' + si,
        opened: true,
        columns: [
          {
            name: 'c' + si,
            fields: Array.from({ length: 10 }, (_, fi) => ({
              fieldname: `f${si}_${fi}`,
              fieldtype: 'Data',
              label: 'F',
            })),
          },
        ],
      })),
    )
    const pass = 5 * 10 * 3

    S.evals = 0
    open(sections, 'P')
    await nextTick()
    expect(S.evals / pass).toBe(1)

    S.evals = 0
    deal.doc.f0_0 = 'typed'
    await nextTick()
    await nextTick()
    expect(S.evals / pass).toBe(1)
  })
})
