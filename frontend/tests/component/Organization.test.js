import {
  defineComponent,
  getCurrentInstance,
  h,
  nextTick,
  reactive,
  ref,
} from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

/**
 * The desktop and mobile organization pages, each mounted per record the way
 * the router does it, over frappe-ui's real resource cache, list resource and
 * Tabs. Children are recorders: the tests read what the page hands them.
 */

const S = vi.hoisted(() => ({
  calls: [],
  callImpl: null,
  docs: {},
  children: {},
  pushed: [],
  reported: [],
}))

vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  call: vi.fn(async (method, args) => {
    S.calls.push({ method, args })
    return S.callImpl ? S.callImpl(method, args) : true
  }),
  toast: { success() {}, error() {}, create() {} },
}))

const recorder = (name) => ({
  default: defineComponent({
    name,
    inheritAttrs: false,
    setup(_, { attrs, slots }) {
      return () => {
        ;(S.children[name] ||= []).push({ ...attrs })
        return h('div', { 'data-stub': name }, slots.default?.({}))
      }
    },
  }),
})
for (const name of [
  'ErrorPage',
  'Icon',
  'LayoutHeader',
  'DeleteLinkedDocModal',
  'CustomActions',
  'EnrichFromWebsite',
  'Resizer',
]) {
  vi.doMock(`@/components/${name}.vue`, () => recorder(name))
}
vi.mock('@/components/ListViews/DealsListView.vue', () =>
  recorder('DealsListView'),
)
vi.mock('@/components/ListViews/ContactsListView.vue', () =>
  recorder('ContactsListView'),
)
vi.mock('@/components/ListViews/EmptyState.vue', () => recorder('EmptyState'))
// Behaves like SidePanelLayout.fieldChange: the new value is written into the
// doc first, then handed to a beforeFieldChange listener if the page bound
// one, or saved straight away if it did not.
vi.mock('@/components/SidePanelLayout.vue', () => ({
  default: defineComponent({
    name: 'SidePanelLayout',
    props: ['sections', 'doctype', 'docname'],
    emits: ['beforeFieldChange', 'afterFieldChange', 'reload'],
    setup(props, { emit }) {
      const listeners = getCurrentInstance().vnode.props ?? {}
      S.panel = {
        props,
        change(fieldname, value) {
          const document = S.docs[props.docname]
          document.doc[fieldname] = value
          if (listeners.onBeforeFieldChange !== undefined)
            emit('beforeFieldChange', { [fieldname]: value })
          else document.save.submit()
        },
      }
      return () => null
    },
  }),
}))
vi.mock('@/data/document', () => ({
  useDocument: (doctype, name) => ({
    document: S.docs[name],
    permissions: { data: {} },
    scripts: { data: [] },
    triggerOnRender: async () => {},
    error: ref(''),
  }),
  markDocumentAsDeleted() {},
  unmarkDocumentAsDeleted() {},
  expireDeletionMarker() {},
}))
vi.mock('@/composables/useDocumentError', () => ({
  useDocumentError: () => ({ errorTitle: ref(''), errorMessage: ref('') }),
}))
vi.mock('@/stores/settings', () => ({ getSettings: () => ({ brand: {} }) }))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog() {}, $socket: { on() {}, off() {} } }),
}))
vi.mock('@/stores/meta', () => ({
  getMeta: () => ({ doctypeMeta: ref({}), getFormattedCurrency: () => '' }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: () => ({}) }),
}))
vi.mock('@/stores/statuses', () => ({
  statusesStore: () => ({ getDealStatus: () => ({}) }),
}))
vi.mock('@/composables/useTimelinePreferences', () => ({
  timestampCell: (v) => v,
}))
vi.mock('@/utils', () => ({
  validateIsImageFile: () => true,
  setupCustomizations: async () => ({}),
  openWebsite() {},
}))
vi.mock('@/utils/view', () => ({ getView: () => null }))
vi.mock('@/utils/reportActionError', () => ({
  reportActionError: (error) => S.reported.push(error),
}))
vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal()),
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: (to) => S.pushed.push(to) }),
}))

const { setConfig, Badge, Button } = await import('frappe-ui')
const { useDoctypeModal } = await import('@/composables/doctypeModal')
const Organization = (await import('@/pages/Organization.vue')).default
const MobileOrganization = (await import('@/pages/MobileOrganization.vue'))
  .default

function organization(name, extra = {}) {
  const doc = { name, organization_name: name, ...extra }
  return reactive({
    doc,
    originalDoc: JSON.parse(JSON.stringify(doc)),
    reload: vi.fn(),
    save: { submit: vi.fn() },
    setValue: { submit: vi.fn() },
  })
}

// An organization whose name starts "Big" has 25 deals and one contact; any
// other has none. Each page gets its own, because the lists are cached per
// organization for the session.
function rowsFor({ doctype, filters }) {
  const org = filters.organization ?? filters.company_name
  if (!org.startsWith('Big')) return []
  if (doctype === 'Contact') return [{ name: 'CONT-1', company_name: org }]
  return Array.from({ length: 25 }, (_, i) => ({
    name: `DEAL-${String(i + 1).padStart(2, '0')}`,
    organization: org,
  }))
}

setConfig('resourceFetcher', async ({ url, params }) => {
  if (url.endsWith('get_sidepanel_sections'))
    return [
      {
        name: 'details_section',
        columns: [
          {
            fields: [
              { fieldname: 'organization_name', fieldtype: 'Data' },
              { fieldname: 'address', fieldtype: 'Link', options: 'Address' },
            ],
          },
        ],
      },
    ]
  if (url === 'frappe.client.get_list') {
    const start = params.limit_start || 0
    return rowsFor(params).slice(start, start + params.limit_page_length)
  }
  if (url === 'frappe.client.get_count') return rowsFor(params).length
  return null
})

async function flush() {
  for (let i = 0; i < 8; i++) {
    await new Promise((r) => setTimeout(r))
    await nextTick()
  }
}

let page
async function visit(Page, organizationId) {
  S.docs[organizationId] ||= organization(organizationId)
  S.children = {}
  page = mount(Page, {
    props: { organizationId },
    stubs: {
      Badge,
      Button,
      ErrorMessage: { render: () => null },
      RouterLink: { render: () => null },
    },
    plugins: [{ install: (app) => (app.config.globalProperties.__ = __) }],
  })
  await flush()
}

afterEach(() => {
  page?.unmount()
  S.docs = {}
  S.calls.length = 0
  S.callImpl = null
  S.pushed.length = 0
  S.reported.length = 0
})

describe.each([
  ['Organization', Organization],
  ['MobileOrganization', MobileOrganization],
])('%s', (name, Page) => {
  it('saves a new address on the organization on screen, not the first one opened', async () => {
    await visit(Page, 'Acme Pumps')
    page.unmount()
    await visit(Page, 'Beta Valves')

    const address = S.panel.props.sections[0].columns[0].fields.find(
      (f) => f.fieldname === 'address',
    )
    address.create('', () => {}) // Address -> Create New
    useDoctypeModal().triggerCallback('afterInsert', { name: 'ADDR-0042' })

    expect(S.docs['Beta Valves'].doc.address).toBe('ADDR-0042')
    expect(S.docs['Beta Valves'].save.submit).toHaveBeenCalled()
    expect(S.docs['Acme Pumps'].doc.address).toBeUndefined()
    expect(S.docs['Acme Pumps'].save.submit).not.toHaveBeenCalled()
  })

  it('renames the record when Organization Name is edited', async () => {
    await visit(Page, 'Acme Pumps')
    S.panel.change('organization_name', 'Acme Pumps SA')
    await flush()
    expect(S.calls).toContainEqual({
      method: 'frappe.client.rename_doc',
      args: {
        doctype: 'CRM Organization',
        old_name: 'Acme Pumps',
        new_name: 'Acme Pumps SA',
      },
    })
    expect(S.pushed.at(-1).params.organizationId).toBe('Acme Pumps SA')
    expect(S.docs['Acme Pumps'].save.submit).not.toHaveBeenCalled()
  })

  it('puts a refused name back, so the next edit does not send it', async () => {
    await visit(Page, 'Gamma Pipes')
    S.callImpl = (method) =>
      method === 'frappe.client.rename_doc'
        ? Promise.reject(new Error('Acme Pumps already exists'))
        : true
    S.panel.change('organization_name', 'Acme Pumps') // taken: refused
    await flush()
    expect(S.reported).toHaveLength(1)
    expect(S.docs['Gamma Pipes'].doc.organization_name).toBe('Gamma Pipes')

    S.panel.change('website', 'https://gamma.example') // the rep carries on
    expect(S.docs['Gamma Pipes'].save.submit).toHaveBeenCalledTimes(1)
    expect(S.docs['Gamma Pipes'].doc.organization_name).toBe('Gamma Pipes')
  })
})
