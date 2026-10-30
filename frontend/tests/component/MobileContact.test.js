import { defineComponent, h, nextTick, reactive, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

/**
 * The mobile contact page, mounted for two contacts in one session the way the
 * router does it (a fresh mount per record), with frappe-ui's real resource
 * cache underneath. The side-panel layout is cached per doctype, so anything
 * the page hangs off it outlives the contact it was built for.
 */

const S = vi.hoisted(() => ({ calls: [], panels: [], docs: {} }))

vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  call: vi.fn(async (method, args) => {
    S.calls.push({ method, args })
    return true
  }),
  toast: { success() {}, error() {}, create() {} },
}))
const blank = (name) => ({
  default: defineComponent({ name, render: () => null }),
})
vi.mock('@/components/Icon.vue', () => blank('Icon'))
vi.mock('@/components/ErrorPage.vue', () => blank('ErrorPage'))
vi.mock('@/components/LayoutHeader.vue', () => blank('LayoutHeader'))
vi.mock('@/components/ListViews/DealsListView.vue', () =>
  blank('DealsListView'),
)
vi.mock('@/components/SidePanelLayout.vue', () => ({
  default: defineComponent({
    name: 'SidePanelLayout',
    props: ['sections', 'doctype', 'docname'],
    setup(props) {
      S.panels.push(props)
      return () => null
    },
  }),
}))
vi.mock('@/data/document', () => ({
  useDocument: (doctype, name) => ({
    document: S.docs[name],
    permissions: { data: {} },
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
vi.mock('@/stores/meta', () => ({
  getMeta: () => ({
    doctypeMeta: ref({ title_field: 'full_name' }),
    getFormattedCurrency: () => '',
  }),
}))
vi.mock('@/stores/global.js', () => ({
  globalStore: () => ({ $dialog() {}, makeCall() {} }),
}))
vi.mock('@/stores/users.js', () => ({
  usersStore: () => ({ getUser: () => ({}) }),
}))
vi.mock('@/stores/organizations.js', () => ({
  organizationsStore: () => ({ getOrganization: () => ({}) }),
}))
vi.mock('@/stores/statuses', () => ({
  statusesStore: () => ({ getDealStatus: () => ({}) }),
}))
vi.mock('@/composables/telephony', () => ({ callEnabled: ref(false) }))
vi.mock('@/composables/useTimelinePreferences', () => ({
  timestampCell: (v) => v,
}))
vi.mock('@/utils', () => ({
  validateIsImageFile: () => true,
  validateEmail: () => true,
  validatePhone: () => true,
}))
vi.mock('@/utils/view', () => ({ getView: () => null }))
vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal()),
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push() {} }),
}))

const { setConfig, Badge, Button } = await import('frappe-ui')
const { useDoctypeModal } = await import('@/composables/doctypeModal')
const MobileContact = (await import('@/pages/MobileContact.vue')).default

function contact(name, email, phone) {
  return reactive({
    doc: {
      name,
      full_name: name,
      email_id: email,
      mobile_no: phone,
      email_ids: [{ name: `${name}-E`, email_id: email }],
      phone_nos: [{ name: `${name}-P`, phone }],
    },
    reload: async () => {},
    save: { submit: vi.fn() },
  })
}
S.docs['CONT-A'] = contact('CONT-A', 'anna@a.co.za', '+27 11 111 1111')
S.docs['CONT-B'] = contact('CONT-B', 'ben@b.co.za', '+27 22 222 2222')

const linkedDeals = {
  'CONT-A': [],
  'CONT-B': [{ name: 'D-1' }, { name: 'D-2' }],
}

// A fresh layout per request, as the server sends it.
setConfig('resourceFetcher', async (o) => {
  if (o.url.endsWith('get_sidepanel_sections'))
    return [
      {
        name: 'details_section',
        columns: [
          {
            fields: [
              { fieldname: 'email_id', fieldtype: 'Data', label: 'Email' },
              { fieldname: 'mobile_no', fieldtype: 'Data', label: 'Mobile' },
              { fieldname: 'address', fieldtype: 'Link', label: 'Address' },
            ],
          },
        ],
      },
    ]
  if (o.url.endsWith('get_linked_deals')) return linkedDeals[o.params.contact]
  return null
})

async function flush() {
  for (let i = 0; i < 8; i++) {
    await new Promise((r) => setTimeout(r))
    await nextTick()
  }
}

let page
async function visit(contactId) {
  S.panels.length = 0
  page = mount(MobileContact, {
    props: { contactId },
    stubs: { Badge, Button, ErrorMessage: { render: () => null } },
    plugins: [{ install: (app) => (app.config.globalProperties.__ = __) }],
  })
  await flush()
  const panel = S.panels.at(-1)
  const field = (fieldname) =>
    panel.sections[0].columns[0].fields.find((f) => f.fieldname === fieldname)
  return { panel, field }
}

afterEach(() => page?.unmount())

describe('MobileContact side panel', () => {
  it('shows and edits the contact on screen, not the first one opened', async () => {
    const a = await visit('CONT-A')
    expect(a.field('email_id').options.map((o) => o.value)).toEqual([
      'anna@a.co.za',
    ])
    page.unmount()

    const b = await visit('CONT-B')
    expect(b.panel.docname).toBe('CONT-B')
    expect(b.field('email_id').options.map((o) => o.value)).toEqual([
      'ben@b.co.za',
    ])
    expect(b.field('mobile_no').options.map((o) => o.value)).toEqual([
      '+27 22 222 2222',
    ])

    S.calls.length = 0
    b.field('email_id').options[0].onClick() // "Set as primary"
    await flush()
    expect(
      S.calls.find((c) => c.method === 'crm.api.contact.set_as_primary').args
        .contact,
    ).toBe('CONT-B')

    b.field('address').create('', () => {}) // Address -> Create New
    useDoctypeModal().triggerCallback('afterInsert', { name: 'ADDR-1' })
    expect(S.docs['CONT-B'].doc.address).toBe('ADDR-1')
    expect(S.docs['CONT-A'].doc.address).toBeUndefined()
    expect(S.docs['CONT-A'].save.submit).not.toHaveBeenCalled()
  })
})
