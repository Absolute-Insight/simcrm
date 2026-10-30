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
