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
    isManager: () => vc.isManager,
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
    // as get_data answers a list view: these two as asked, kanban_fields
    // parsed (the store holds it as the string '[]')
    column_field: params?.column_field,
    title_field: params?.title_field,
    kanban_fields: [],
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
    isManager: false,
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
    kanban_fields: '[]',
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
  const more = ref(1)
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
        loadMore: more.value,
        'onUpdate:loadMore': (v) => (more.value = v),
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
    loadMore: () => more.value++,
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
    // the page on screen, read back from the first answer
    expect(query.get('page_length')).toBe('20')
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

describe('coming back to a saved view with nothing unsaved', () => {
  // Both leave the list fetching with the params onSuccess built from
  // get_data's answer, kanban_fields parsed, where the store holds a string.
  it('after Load More, offers nothing to save', async () => {
    savedView(15)
    setRoute({ view: 15 })
    const first = await mountVC()
    first.loadMore()
    await settle()
    expect(first.button('Save Changes')).toBeNull()
    first.unmount()
    const back = await mountVC()
    expect(back.button('Save Changes')).toBeNull()
  })

  it('after its change was saved, offers nothing to save', async () => {
    savedView(16)
    setRoute({ view: 16 })
    const first = await mountVC()
    first.vc().applyFilter({
      event: click(),
      idx: 1,
      column: { key: 'status', type: 'Select' },
      item: 'Open',
      firstColumn: { key: 'lead_name' },
    })
    await settle()
    first.button('Save Changes').click()
    await settle()
    // the dialog's Save Changes: the server stores it, then afterUpdate
    const dialog = vc.children.ViewModal
    vc.views[16].filters = JSON.stringify(dialog.view.filters)
    dialog.options.afterUpdate({ ...dialog.view })
    await settle()
    expect(first.button('Save Changes')).toBeNull()
    first.unmount()
    const back = await mountVC()
    expect(vc.fetches.at(-1).filters).toEqual({ status: 'Open' })
    expect(back.button('Save Changes')).toBeNull()
  })

  it('a kanban view, after its card fields were saved', async () => {
    // get_data fills a blank kanban title with a default; the store holds
    // kanban_fields as the JSON string the server dumped
    vc.getData = (params) =>
      later({
        ...payload(params),
        title_field: params.title_field || 'lead_name',
        kanban_fields: JSON.parse(JSON.stringify(params.kanban_fields)),
      })
    savedView(18, { type: 'kanban', title_field: '', kanban_fields: '[]' })
    setRoute({ view: 18 })
    route.params = { viewType: 'kanban' }
    const options = { allowedViews: ['list', 'kanban'] }
    const first = await mountVC({ options })
    vc.children.KanbanSettings.onUpdate({
      column_field: 'status',
      title_field: 'lead_name',
      kanban_fields: ['name', 'status'],
    })
    await settle()
    first.button('Save Changes').click()
    await settle()
    // the server stores the dialog's view, kanban_fields through json.dumps
    const dialog = vc.children.ViewModal
    Object.assign(vc.views[18], {
      title_field: dialog.view.title_field,
      kanban_fields: '["name", "status"]',
    })
    dialog.options.afterUpdate({ ...dialog.view })
    await settle()
    first.unmount()
    const back = await mountVC({ options })
    expect(vc.fetches.at(-1).kanban_fields).toEqual(['name', 'status'])
    expect(back.button('Save Changes')).toBeNull()
  })
})

describe('Load More', () => {
  it('asks for the next page on the first visit to a view', async () => {
    savedView(17)
    setRoute({ view: 17 })
    const m = await mountVC()
    m.loadMore()
    await settle()
    expect(vc.fetches.at(-1).page_length).toBe(40)
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
    vc.calls.filter(([method]) => method.endsWith('crm_view_settings.update'))

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
    expect(saved.columns).toEqual([
      { key: 'name', label: 'Name', type: 'Data' },
    ])
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

describe('Reset Changes in Columns', () => {
  const ORIGINAL = {
    columns: [{ key: 'name', label: 'Name', type: 'Data' }],
    rows: ['name'],
  }
  const ADDED = {
    columns: [...ORIGINAL.columns, { key: 'status', label: 'Status' }],
    rows: ['name', 'status'],
  }
  const standardSaves = () =>
    vc.calls.filter(([method]) => method.endsWith('standard_view'))

  // getParams() read the saved view back, which by then holds the added column
  // or nothing, and overwrote both the request and the view about to be saved.
  it('asks for and saves the columns it restored', async () => {
    setRoute()
    const m = await mountVC()
    vc.children.ColumnSettings.onUpdate({ ...ADDED, reload: true })
    await settle()

    vc.children.ColumnSettings.onUpdate({
      ...ORIGINAL,
      isDefault: false,
      reload: true,
      reset: true,
    })
    await settle()

    expect(vc.fetches.at(-1).columns).toEqual(ORIGINAL.columns)
    expect(vc.fetches.at(-1).rows).toEqual(ORIGINAL.rows)
    const saved = standardSaves().at(-1)[1].view
    expect(saved.columns).toEqual(ORIGINAL.columns)
    expect(saved.rows).toEqual(ORIGINAL.rows)
    expect(saved.load_default_columns).toBe(false)
    m.unmount()
  })

  it('Reset to Default still asks for the defaults', async () => {
    setRoute()
    const m = await mountVC()
    vc.children.ColumnSettings.onUpdate({
      ...ADDED,
      isDefault: true,
      reload: true,
    })
    await settle()

    const saved = standardSaves().at(-1)[1].view
    expect(saved.columns).toBe('')
    expect(saved.load_default_columns).toBe(true)
    m.unmount()
  })

  // `_view?.row || true` read a column that does not exist: every view went
  // back to the server marked as using the default columns.
  it('a filter saved on a customised view does not mark it default', async () => {
    vc.isManager = true
    savedView(31, { public: 1, load_default_columns: 0 })
    setRoute({ view: 31 })
    const m = await mountVC()
    m.vc().applyFilter({
      event: click(),
      idx: 1,
      column: { key: 'status', type: 'Select' },
      item: 'Open',
      firstColumn: { key: 'lead_name' },
    })
    await settle()
    m.button('Save Changes').click()
    await settle()
    expect(vc.children.ViewModal.view.load_default_columns).toBe(0)
    m.unmount()
  })
})

describe('the view dialog is handed a copy', () => {
  it('a cancelled Duplicate leaves the original view as it was', async () => {
    const original = savedView(51, { label: 'Hot leads' })
    setRoute({ view: 51 })
    const m = await mountVC()
    m.vc()
      .viewActions({ name: 51, label: 'Hot leads' }, () => {})[0]
      .options.find((o) => o.label === 'Duplicate')
      .onClick()
    await settle()
    expect(vc.children.ViewModal.view).toMatchObject({
      label: 'Hot leads (New)',
      mode: 'duplicate',
    })
    // the dialog is dismissed: nothing was saved
    expect(original.label).toBe('Hot leads')
    expect(original.mode).toBeUndefined()
  })

  it('a cancelled Edit leaves the stored view as it was', async () => {
    const original = savedView(52)
    setRoute({ view: 52 })
    const m = await mountVC()
    m.vc()
      .viewActions({ name: 52, label: 'View 52' }, () => {})[0]
      .options.find((o) => o.label === 'Edit')
      .onClick()
    await settle()
    expect(vc.children.ViewModal.view).toMatchObject({
      name: 52,
      mode: 'edit',
    })
    expect(vc.children.ViewModal.view).not.toBe(original)
    expect(original.mode).toBeUndefined()
  })

  it('a cancelled Create View leaves the view on screen as it was', async () => {
    savedView(61, { label: 'My Gauteng leads' })
    setRoute({ view: 61 })
    const m = await mountVC()
    m.vc()
      .viewsDropdownOptions.find((g) => g.group === 'Actions')
      .options.find((o) => o.label === 'Create View')
      .onClick()
    await settle()
    expect(vc.children.ViewModal.view).toMatchObject({
      name: '',
      label: '',
      mode: 'create',
    })
    // dismissed; an unsaved filter, then Save Changes saves view 61
    m.vc().applyFilter({
      event: click(),
      idx: 1,
      column: { key: 'status', type: 'Select' },
      item: 'Open',
      firstColumn: { key: 'lead_name' },
    })
    await settle()
    m.button('Save Changes').click()
    await settle()
    expect(vc.children.ViewModal.view).toMatchObject({
      name: 61,
      label: 'My Gauteng leads',
      mode: 'edit',
    })
  })

  it('a cancelled Save Changes leaves the view on screen as it was', async () => {
    vc.isManager = true
    savedView(63, { public: 1 })
    setRoute({ view: 63 })
    const m = await mountVC()
    m.vc().applyFilter({
      event: click(),
      idx: 1,
      column: { key: 'status', type: 'Select' },
      item: 'Open',
      firstColumn: { key: 'lead_name' },
    })
    await settle()
    m.button('Save Changes').click()
    await settle()
    expect(vc.children.ViewModal.view).toMatchObject({
      name: 63,
      filters: { status: 'Open' },
      mode: 'edit',
    })
    // dismissed: it is still a public view, whose columns wait for Save
    // Changes like everything else rather than saving on a resize
    m.resize()
    await settle()
    expect(
      vc.calls.filter(([method]) =>
        method.endsWith('crm_view_settings.update'),
      ),
    ).toEqual([])
    expect(m.button('Save Changes')).not.toBeNull()
  })
})

describe('a rename saved from the view dialog', () => {
  // ViewModal's Save Changes: the server stores the draft, then afterUpdate
  // gets it. The views store re-read lands while get_data is still out, so
  // the getView watcher's reload() stands down and rebuilds nothing.
  function saveDialog(changes) {
    const draft = { ...vc.children.ViewModal.view, ...changes }
    Object.assign(vc.views[draft.name], {
      label: draft.label,
      icon: draft.icon,
    })
    vc.children.ViewModal.options.afterUpdate(draft)
  }
  const filterOpen = (m) =>
    m.vc().applyFilter({
      event: click(),
      idx: 1,
      column: { key: 'status', type: 'Select' },
      item: 'Open',
      firstColumn: { key: 'lead_name' },
    })
  const editFromMenu = (m, name, label) =>
    m
      .vc()
      .viewActions({ name, label }, () => {})[0]
      .options.find((o) => o.label === 'Edit')
      .onClick()

  it('the next Save Changes keeps the new name and icon', async () => {
    savedView(71, { label: 'Hot leads', icon: 'flame' })
    setRoute({ view: 71 })
    const m = await mountVC()
    filterOpen(m)
    await settle()
    m.button('Save Changes').click()
    await settle()
    saveDialog({ label: 'Warm leads', icon: 'sun' })
    await settle()

    vc.children.SortBy.onUpdate('creation desc')
    await settle()
    m.button('Save Changes').click()
    await settle()
    expect(vc.children.ViewModal.view).toMatchObject({
      name: 71,
      label: 'Warm leads',
      icon: 'sun',
      filters: { status: 'Open' },
      order_by: 'creation desc',
    })
  })

  it('so does an Edit from the views menu of the view on screen', async () => {
    savedView(72, { label: 'Hot leads', icon: 'flame' })
    setRoute({ view: 72 })
    const m = await mountVC()
    editFromMenu(m, 72, 'Hot leads')
    await settle()
    saveDialog({ label: 'Warm leads', icon: 'sun' })
    await settle()

    filterOpen(m)
    await settle()
    m.button('Save Changes').click()
    await settle()
    expect(vc.children.ViewModal.view).toMatchObject({
      name: 72,
      label: 'Warm leads',
      icon: 'sun',
    })
  })

  it('renaming another view leaves the one on screen as it was', async () => {
    savedView(73, { label: 'Mine', icon: 'star' })
    savedView(74, { label: 'Theirs' })
    setRoute({ view: 73 })
    const m = await mountVC()
    editFromMenu(m, 74, 'Theirs')
    await settle()
    saveDialog({ label: 'Renamed' })
    await settle()

    filterOpen(m)
    await settle()
    m.button('Save Changes').click()
    await settle()
    expect(vc.children.ViewModal.view).toMatchObject({
      name: 73,
      label: 'Mine',
      icon: 'star',
    })
  })
})

describe('clicking a cell filters on the stored value', () => {
  async function clickCell(doctype, doc, column, item) {
    setRoute({ name: doctype })
    vc.getData = (params) => later(payload(params, [doc]))
    const m = await mountVC({ doctype })
    m.vc().applyFilter({
      event: click(),
      idx: 1,
      column,
      item,
      row: { name: doc.name }, // the display row the list view rendered
      firstColumn: { key: 'name' },
    })
    await settle()
    return vc.fetches.at(-1).filters[column.key]
  }

  it('a call status shown as its label', async () => {
    const log = { name: 'CL-1', status: 'Busy', type: 'Outgoing' }
    const status = { key: 'status', type: 'Select' }
    expect(
      await clickCell('CRM Call Log', log, status, {
        label: 'Declined',
        color: 'orange',
      }),
    ).toBe('Busy')
  })

  it('a User link shown as a full name', async () => {
    const log = { name: 'CL-2', receiver: 'rep@example.com' }
    const receiver = { key: 'receiver', type: 'Link' }
    expect(
      await clickCell('CRM Call Log (receiver)', log, receiver, {
        label: 'Rep One',
      }),
    ).toBe('rep@example.com')
  })

  it('a website shown without its scheme', async () => {
    const org = { name: 'Acme', website: 'https://www.acme-pumps.co.za' }
    const website = { key: 'website', type: 'Data' }
    expect(
      await clickCell(
        'CRM Organization (website)',
        org,
        website,
        'acme-pumps.co.za',
      ),
    ).toBe('https://www.acme-pumps.co.za')
  })

  it('an amount shown formatted', async () => {
    const deal = { name: 'CRM-DEAL-1', annual_revenue: 1500000 }
    const revenue = { key: 'annual_revenue', type: 'Currency' }
    expect(
      await clickCell('CRM Deal (revenue)', deal, revenue, 'R 1,500,000.00'),
    ).toBe(1500000)
  })

  it('a column the record does not carry still filters on what it shows', async () => {
    const lead = { name: 'CRM-LEAD-1', status: 'Open' }
    expect(
      await clickCell(
        'CRM Lead (no row)',
        lead,
        { key: 'territory', type: 'Link' },
        'Gauteng',
      ),
    ).toBe('Gauteng')
  })
})
