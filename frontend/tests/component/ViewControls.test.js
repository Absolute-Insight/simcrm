import { defineComponent, h, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// ViewControls mounted the way a list page mounts it: the page owns `ref({})`
// and binds it with v-model, ViewControls replaces it with the list resource.
// frappe-ui's real createResource runs, fed by a fake get_data; the toolbar's
// children are stubs that record what they were given, so a test can drive
// them the way the real child would (SortBy emitting `update`, and so on).

const { vc, route } = vi.hoisted(() => ({
  vc: {},
  route: { name: 'Leads', params: { viewType: 'list' }, query: {} },
}))

vi.mock('frappe-ui', async (importOriginal) => {
  const actual = await importOriginal()
  const { recorder } = await import('./recorder.js')
  return {
    ...actual,
    Combobox: recorder('Combobox', vc),
    Tooltip: recorder('Tooltip', vc),
    Dropdown: recorder('Dropdown', vc),
    call: (method, args) => {
      vc.calls.push([method, JSON.parse(JSON.stringify(args ?? null))])
      return Promise.resolve({})
    },
    toast: { success() {}, error() {} },
    usePageMeta: () => {},
  }
})
vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  const live = reactive(route)
  return { useRoute: () => live, useRouter: () => ({ push: () => {} }) }
})
vi.mock('vuedraggable', () => ({ default: { render: () => null } }))
vi.mock('@/stores/views', () => ({
  viewsStore: () => ({
    reload: () => Promise.resolve(),
    getDefaultView: () => null,
    getView: (view) => (view ? vc.views[view] : null),
  }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    isManager: () => false,
    getUser: () => ({ name: 'rep@example.com' }),
  }),
}))
vi.mock('@/stores/settings', () => ({ getSettings: () => ({ brand: {} }) }))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({
    $dialog: () => {},
    $socket: { on: (event, fn) => (vc.socket[event] = fn), off() {} },
  }),
}))
vi.mock('@/stores/organizations', () => ({
  organizationsStore: () => ({ organizations: { reload() {} } }),
}))
vi.mock('@/stores/statuses', () => ({
  statusesStore: () => ({
    getLeadStatus: () => null,
    getDealStatus: () => null,
  }),
}))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({ getFields: () => [] }) }))
vi.mock('@/composables/settings', async () => ({
  isMobileView: (await import('vue')).ref(false),
}))
vi.mock('@/utils', () => ({ isEmoji: () => false }))
vi.mock('@/utils/reportActionError', () => ({
  reportActionError: (e, message) => vc.actionErrors.push(message),
}))
vi.mock('@/utils/taskClosing', () => ({
  collectClosingValues: async () => null,
  needsClosingNote: () => false,
}))
for (const child of [
  'QuickFilterField',
  'Modals/ViewModal',
  'SortBy',
  'Filter',
  'GroupBy',
  'FadedScrollableDiv',
  'ColumnSettings',
  'Kanban/KanbanSettings',
  'Modals/LostReasonModal',
]) {
  vi.doMock(`@/components/${child}.vue`, async () => {
    const { recorder } = await import('./recorder.js')
    return { default: recorder(child.split('/').pop(), vc) }
  })
}

const { setConfig } = await import('frappe-ui')
const { default: ViewControls } = await import('@/components/ViewControls.vue')

// Resolves after a macrotask, like a network round-trip.
const later = (value, ms = 1) =>
  new Promise((resolve) => setTimeout(() => resolve(value), ms))

function payload(params, data = []) {
  return {
    data,
    columns: [{ key: 'name', label: 'Name', type: 'Data' }],
    rows: ['name'],
    views: [],
    page_length: params?.page_length || 20,
    page_length_count: params?.page_length_count || 20,
    total_count: data.length,
    view_type: params?.view?.view_type || 'list',
  }
}

setConfig('resourceFetcher', (options) => {
  if (options.url === 'crm.api.doc.get_data') {
    vc.fetches.push(JSON.parse(JSON.stringify(options.params ?? null)))
    return vc.getData(options.params, options.signal)
  }
  if (options.url === 'crm.api.doc.get_quick_filters') {
    return Promise.resolve(JSON.parse(JSON.stringify(vc.quickFilters)))
  }
  return Promise.resolve(null)
})

beforeEach(() => {
  Object.assign(vc, {
    views: {},
    fetches: [],
    calls: [],
    children: {},
    socket: {},
    actionErrors: [],
    quickFilters: [],
    getData: (params) => later(payload(params)),
  })
})

async function settle(n = 6) {
  for (let i = 0; i < n; i++) {
    await new Promise((resolve) => setTimeout(resolve, 3))
  }
}

function setRoute({ name = 'Leads', view } = {}) {
  route.name = name
  route.params = { viewType: 'list' }
  route.query = view === undefined ? {} : { view: String(view) }
}

// A private saved view, as the views store holds it.
function savedView(name, fields = {}) {
  vc.views[name] = {
    name,
    label: `View ${name}`,
    type: 'list',
    filters: '{}',
    order_by: 'modified desc',
    columns: '',
    rows: '',
    public: 0,
    pinned: 0,
    is_standard: 0,
    ...fields,
  }
  return vc.views[name]
}

const Button = defineComponent({
  props: { label: String, icon: String, loading: Boolean, tooltip: String },
  emits: ['click'],
  setup:
    (props, { emit, slots }) =>
    () =>
      h(
        'button',
        {
          'data-label': props.label || '',
          'data-icon': props.icon || '',
          onClick: (e) => emit('click', e),
        },
        props.label || slots.default?.(),
      ),
})
const Dialog = defineComponent({
  props: { open: Boolean, actions: Array, title: String },
  setup:
    (props, { slots }) =>
    () =>
      props.open
        ? h('div', [
            slots.default?.(),
            ...(props.actions || []).map((a) =>
              h(
                'button',
                { 'data-action': a.label, onClick: a.onClick },
                a.label,
              ),
            ),
          ])
        : null,
})

async function mountVC({
  doctype = 'CRM Lead',
  filters = {},
  options = { allowedViews: ['list'] },
} = {}) {
  const list = ref({})
  const resize = ref(1)
  const vm = ref(null)
  const errors = []
  const Page = defineComponent({
    setup: () => () =>
      h(ViewControls, {
        ref: vm,
        modelValue: list.value,
        'onUpdate:modelValue': (v) => (list.value = v),
        resizeColumn: resize.value,
        'onUpdate:resizeColumn': (v) => (resize.value = v),
        doctype,
        filters,
        options,
      }),
  })
  const w = mount(Page, {
    stubs: { Button, Dialog, FormControl: { render: () => null } },
    plugins: [
      (app) => {
        app.config.errorHandler = (e) => errors.push(e)
        app.config.warnHandler = () => {}
      },
    ],
  })
  await settle()
  return {
    ...w,
    errors,
    vc: () => vm.value,
    list: () => list.value,
    resize: () => resize.value++,
    button: (label) => w.el.querySelector(`button[data-label="${label}"]`),
  }
}

const click = () => ({
  stopPropagation() {},
  preventDefault() {},
  target: { closest: () => null },
})

describe('quick filters', () => {
  it('a number filter on a numeric quick-filter field renders', async () => {
    vc.quickFilters = [
      { label: 'Employees', fieldname: 'employee_count', fieldtype: 'Int' },
    ]
    setRoute({ name: 'Organizations' })
    const m = await mountVC({ doctype: 'CRM Organization' })
    m.vc().applyFilter({
      event: click(),
      idx: 2,
      column: { key: 'employee_count', type: 'Int' },
      item: 42,
      firstColumn: { key: 'organization_name' },
    })
    await settle()
    expect(m.errors.map(String)).toEqual([])
    expect(vc.children.QuickFilterField.filter.value).toBe(42)
  })
})

describe('export', () => {
  it('sends every selected name intact, whatever it contains', async () => {
    setRoute({ name: 'Organizations' })
    const m = await mountVC({ doctype: 'CRM Organization (export)' })
    const selected = [
      'Smith & Sons (Pty) Ltd',
      'A+B Engineering',
      'Unit #4 Holdings',
      '100% Pumps',
    ]
    m.vc().updateSelections(new Set(selected))
    vc.children.Dropdown.options[0].options
      .find((o) => o.label === 'Export')
      .onClick()
    await settle()

    let url = null
    const location = window.location
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: {
        set href(v) {
          url = v
        },
      },
    })
    try {
      m.el.querySelector('button[data-action="Download"]').click()
    } finally {
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: location,
      })
    }

    // the query string as the server parses it
    const query = new URL(url, 'https://crm.example').searchParams
    expect(JSON.parse(query.get('selected_items'))).toEqual(selected)
    expect(query.get('doctype')).toBe('CRM Organization (export)')
    expect(JSON.parse(query.get('fields'))).toEqual(['name'])
    expect(query.get('order_by')).toBe('modified desc')
  })
})

describe('coming back to a saved view with an unsaved change', () => {
  async function leaveWithUnsavedFilter(view) {
    savedView(view)
    setRoute({ view })
    const first = await mountVC()
    first.vc().applyFilter({
      event: click(),
      idx: 1,
      column: { key: 'status', type: 'Select' },
      item: 'Open',
      firstColumn: { key: 'lead_name' },
    })
    await settle()
    expect(first.button('Save Changes')).not.toBeNull()
    first.unmount() // open a lead...
    return mountVC() // ...and come back
  }

  it('keeps the change and still offers to save it', async () => {
    const back = await leaveWithUnsavedFilter(7)
    expect(vc.fetches.at(-1).filters).toEqual({ status: 'Open' })
    back.button('Save Changes').click()
    await settle()
    expect(vc.children.ViewModal.view.filters).toEqual({ status: 'Open' })
  })

  it('keeps the change through the next edit', async () => {
    await leaveWithUnsavedFilter(8)
    vc.children.SortBy.onUpdate('creation desc')
    await settle()
    expect(vc.fetches.at(-1).order_by).toBe('creation desc')
    expect(vc.fetches.at(-1).filters).toEqual({ status: 'Open' })
  })

  it('a quick filter typed before the first load lands applies', async () => {
    vc.quickFilters = [
      { label: 'Name', fieldname: 'lead_name', fieldtype: 'Data' },
    ]
    savedView(9)
    setRoute({ view: 9 })
    vc.getData = () => new Promise(() => {}) // the first load is still out
    const m = await mountVC({ doctype: 'CRM Deal' })
    const qf = vc.children.QuickFilterField
    qf.onApplyQuickFilter(qf.filter, 'smith')
    await settle()
    expect(m.errors.map(String)).toEqual([])
    expect(vc.fetches.at(-1).filters).toEqual({
      lead_name: ['LIKE', '%smith%'],
    })
  })
})

describe('Refresh', () => {
  async function withUnsavedFilter(view, doctype = 'CRM Lead') {
    savedView(view)
    setRoute({ view })
    const m = await mountVC({ doctype })
    m.vc().applyFilter({
      event: click(),
      idx: 1,
      column: { key: 'territory', type: 'Link' },
      item: 'Gauteng',
      firstColumn: { key: 'lead_name' },
    })
    await settle()
    return m
  }

  it('re-fetches the filter on screen instead of reverting it', async () => {
    const m = await withUnsavedFilter(31)
    m.el.querySelector('button[data-icon="lucide-refresh-ccw"]').click()
    await settle()
    expect(vc.fetches.at(-1).filters).toEqual({ territory: 'Gauteng' })
    expect(m.button('Save Changes')).not.toBeNull()
  })

  it('so does the refresh after an enrichment finishes', async () => {
    await withUnsavedFilter(32, 'CRM Organization')
    vc.socket.domain_enrichment_progress({
      status: 'completed',
      reference_doctype: 'CRM Organization',
    })
    await settle()
    expect(vc.fetches.at(-1).filters).toEqual({ territory: 'Gauteng' })
  })

  it('Cancel still goes back to the saved view', async () => {
    const m = await withUnsavedFilter(33)
    m.button('Cancel').click()
    await settle()
    expect(vc.fetches.at(-1).filters).toEqual({})
    expect(m.button('Save Changes')).toBeNull()
  })
})

describe('overlapping reloads', () => {
  it('show the rows for the latest filter, not the last response', async () => {
    vc.quickFilters = [
      { label: 'Status', fieldname: 'status', fieldtype: 'Select' },
    ]
    savedView(41)
    setRoute({ view: 41 })
    const m = await mountVC({ doctype: 'CRM Task' })

    // The server answers what was sent, when told to. Like fetch(), an
    // aborted request rejects with an AbortError.
    const pending = []
    vc.getData = (params, signal) =>
      new Promise((resolve, reject) => {
        const rows = [{ name: `row-for-${params.filters.status}` }]
        pending.push(() => resolve(payload(params, rows)))
        signal?.addEventListener('abort', () =>
          reject(new DOMException('aborted', 'AbortError')),
        )
      })
    const qf = vc.children.QuickFilterField
    qf.onApplyQuickFilter(qf.filter, 'Qualified') // request A
    qf.onApplyQuickFilter(qf.filter, 'Lost') // request B, the current choice
    pending[1]() // B answers first
    await settle()
    pending[0]() // the slower A answers last
    await settle()

    expect(m.list().params.filters).toEqual({ status: 'Lost' })
    expect(m.list().data.data).toEqual([{ name: 'row-for-Lost' }])
  })
})

describe('resizing a column on a private saved view', () => {
  const updates = () =>
    vc.calls.filter(([method]) =>
      method.endsWith('crm_view_settings.update'),
    )

  it('saves the column layout, not an unsaved filter or sort', async () => {
    savedView(21, { filters: '{"status": "Open"}' })
    setRoute({ view: 21 })
    const m = await mountVC()
    m.vc().applyFilter({
      event: click(),
      idx: 1,
      column: { key: 'lead_owner', type: 'Link' },
      item: 'other.rep@example.com',
      firstColumn: { key: 'lead_name' },
    })
    vc.children.SortBy.onUpdate('creation desc')
    await settle()

    m.resize() // a column edge dragged
    await settle()

    expect(updates()).toHaveLength(1)
    const saved = updates()[0][1].view
    expect(saved.name).toBe(21)
    expect(JSON.parse(saved.filters)).toEqual({ status: 'Open' })
    expect(saved.order_by).toBe('modified desc')
    expect(saved.columns).toEqual([{ key: 'name', label: 'Name', type: 'Data' }])
    // the filter and sort are still unsaved, and still on screen
    expect(m.button('Cancel')).not.toBeNull()
    expect(vc.fetches.at(-1).filters).toEqual({
      status: 'Open',
      lead_owner: 'other.rep@example.com',
    })
  })

  it('with nothing else unsaved, leaves nothing to save', async () => {
    savedView(22)
    setRoute({ view: 22 })
    const m = await mountVC()
    m.resize()
    await settle()
    expect(updates()).toHaveLength(1)
    expect(m.button('Save Changes')).toBeNull()
  })
})
