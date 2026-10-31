import { defineComponent, h, nextTick, reactive, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

/**
 * The phone-width Deal and Lead pages, mounted per record the way the router
 * does it, over frappe-ui's real resource cache and real Tabs. The side-panel
 * layout is cached per doctype for the session, so anything one deal hangs off
 * it shows on the next. SidePanelLayout renders the page's section slots, so
 * the contacts the page draws there can be read back.
 */

const S = vi.hoisted(() => ({
  docs: {},
  calls: [],
  panels: [],
  delay: { sections: 1, contacts: 1 },
  contacts: {},
}))

vi.mock('frappe-ui', async (importOriginal) => {
  const real = await importOriginal()
  const { defineComponent, h } = await import('vue')
  return {
    ...real,
    call: vi.fn(async (method, args) => {
      S.calls.push({ method, args })
      return true
    }),
    toast: { success() {}, error() {}, create() {} },
    Breadcrumbs: defineComponent({ name: 'Breadcrumbs', render: () => null }),
    // Keeps its options on the element, where a test can pick one.
    Dropdown: defineComponent({
      name: 'Dropdown',
      inheritAttrs: false,
      setup:
        (_, { attrs, slots }) =>
        () =>
          h(
            'div',
            { 'data-stub': 'Dropdown', '.options': attrs.options },
            slots.default?.({ open: false }),
          ),
    }),
  }
})

const blank = (name) => ({
  default: defineComponent({ name, render: () => null }),
})
for (const name of [
  'DeleteLinkedDocModal',
  'ErrorPage',
  'Icon',
  'LayoutHeader',
  'AssignTo',
  'SLASection',
  'RecordSuggestions',
  'CustomActions',
  'Activities/Activities',
  'Modals/OrganizationModal',
  'Modals/LostReasonModal',
  'Modals/ContactModal',
  'Modals/ConvertToDealModal',
  'Controls/Link',
]) {
  vi.doMock(`@/components/${name}.vue`, () => blank(name))
}
vi.mock('@/components/CollapsibleSection.vue', () => ({
  default: defineComponent({
    name: 'CollapsibleSection',
    setup:
      (_, { slots }) =>
      () =>
        h('div', [
          slots.header?.({ opened: true, toggle() {} }),
          slots.default?.(),
        ]),
  }),
}))
vi.mock('@/components/SidePanelLayout.vue', () => ({
  default: defineComponent({
    name: 'SidePanelLayout',
    props: ['sections', 'doctype', 'docname'],
    setup(props, { slots }) {
      S.panels.push(props)
      return () =>
        h(
          'div',
          (props.sections || []).map((section) =>
            h('section', { 'data-section': section.name }, [
              slots.default?.({ section }),
            ]),
          ),
        )
    },
  }),
}))

vi.mock('@/data/document', () => ({
  useDocument: (doctype, name) => {
    S.docs[name] ||= reactive({
      doc: { name, doctype, status: 'Qualification' },
      save: { submit: vi.fn() },
    })
    return {
      document: S.docs[name],
      assignees: { data: [], reload() {} },
      permissions: { data: {} },
      scripts: { data: [] },
      error: ref(''),
      triggerOnChange: async () => {},
      triggerOnRender: async () => {},
    }
  },
}))
vi.mock('@/stores/settings', () => ({ getSettings: () => ({ brand: {} }) }))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog() {}, $socket: { on() {}, off() {} } }),
}))
vi.mock('@/stores/statuses', () => ({
  statusesStore: () => ({
    statusOptions: () => [],
    getDealStatus: () => ({ type: 'Open', color: '' }),
    getLeadStatus: () => ({ type: 'Open', color: '' }),
  }),
}))
vi.mock('@/stores/meta', () => ({
  getMeta: () => ({ doctypeMeta: ref({}) }),
}))
// A phone in portrait, settable: the real one follows a matchMedia query.
vi.mock('@/composables/settings', async (importOriginal) => {
  const { ref } = await import('vue')
  return { ...(await importOriginal()), isMobileView: ref(true) }
})
vi.mock('@/composables/whatsapp', () => ({ whatsappEnabled: ref(false) }))
vi.mock('@/composables/telephony', () => ({ callEnabled: ref(false) }))
vi.mock('@/utils', () => ({
  setupCustomizations: async () => ({}),
  isTranslatable: () => false,
}))
vi.mock('@/utils/view', () => ({ getView: () => null }))
vi.mock('vue-router', async (importOriginal) => {
  const { reactive } = await import('vue')
  const route = reactive({ hash: '#details', query: {}, params: {} })
  return {
    ...(await importOriginal()),
    useRoute: () => route,
    useRouter: () => ({ push: (to) => (route.hash = to.hash || route.hash) }),
  }
})

const { setConfig } = await import('frappe-ui')
const { isMobileView } = await import('@/composables/settings')
const MobileDeal = (await import('@/pages/MobileDeal.vue')).default
const MobileLead = (await import('@/pages/MobileLead.vue')).default

// The layout as get_sidepanel_sections sends it: a layout field's `name` is
// its DocField row id, and the contacts section comes with no contacts.
const layout = [
  { name: 'contacts_section', label: 'Contacts', contacts: [] },
  {
    name: 'organization_section',
    label: 'Organization Details',
    columns: [
      {
        name: 'column_1',
        fields: [
          {
            name: 'k3v9q1d2ab',
            fieldname: 'organization',
            fieldtype: 'Link',
            options: 'CRM Organization',
          },
        ],
      },
    ],
  },
]
S.contacts = {
  'DEAL-A': [
    { name: 'alice@a', full_name: 'Alice Primary', is_primary: 1 },
    { name: 'bob@a', full_name: 'Bob Second', is_primary: 0 },
  ],
  'DEAL-B': [{ name: 'carol@b', full_name: 'Carol OfB', is_primary: 1 }],
  'DEAL-C': [{ name: 'dan@c', full_name: 'Dan OfC', is_primary: 1 }],
}
const later = (value, ms) =>
  new Promise((r) => setTimeout(() => r(structuredClone(value)), ms))
setConfig('resourceFetcher', ({ url, params }) => {
  if (url.endsWith('get_sidepanel_sections'))
    return later(layout, S.delay.sections)
  if (url.endsWith('get_deal_contacts') && params.name === 'DEAL-REFUSED')
    return Promise.reject(new Error('refused'))
  if (url.endsWith('get_deal_contacts'))
    return later(S.contacts[params.name] || [], S.delay.contacts)
  return later([], 1)
})

async function flush(ms = 0) {
  if (ms) await new Promise((r) => setTimeout(r, ms))
  for (let i = 0; i < 8; i++) {
    await new Promise((r) => setTimeout(r, 2))
    await nextTick()
  }
}

let page
async function visit(Page, props) {
  S.panels.length = 0
  page = mount(Page, {
    props,
    stubs: {
      Badge: defineComponent({
        props: ['label'],
        setup: (props) => () => h('span', props.label),
      }),
      Button: defineComponent({
        inheritAttrs: false,
        setup:
          (_, { slots }) =>
          () =>
            h('button', slots.default?.()),
      }),
      Tooltip: defineComponent({
        setup:
          (_, { slots }) =>
          () =>
            h('div', slots.default?.()),
      }),
    },
  })
  await flush()
}

const contactsText = () =>
  page.el
    .querySelector('[data-section="contacts_section"]')
    ?.textContent.replace(/\s+/g, ' ')
    .trim()

const tabLabels = () =>
  [...page.el.querySelectorAll('[role="tab"]')].map((t) => t.textContent.trim())

afterEach(() => {
  page?.unmount()
  S.docs = {}
  S.calls.length = 0
  S.delay.sections = S.delay.contacts = 1
  isMobileView.value = true
})

describe('MobileDeal contacts', () => {
  it('leaves no rejection unhandled when they are refused', async () => {
    const rejections = []
    const onRejection = (reason) => rejections.push(reason)
    process.on('unhandledRejection', onRejection)
    await visit(MobileDeal, { dealId: 'DEAL-REFUSED' })
    await new Promise((r) => setTimeout(r, 20))
    process.off('unhandledRejection', onRejection)
    expect(rejections).toEqual([])
  })

  it('sets the tapped contact as primary, and offers it only on the others', async () => {
    await visit(MobileDeal, { dealId: 'DEAL-A' })
    const [alice, bob] = [
      ...page.el.querySelectorAll(
        '[data-section="contacts_section"] [data-stub="Dropdown"]',
      ),
    ].map((d) => d.options)
    expect(alice.map((o) => o.label)).toEqual(['Delete'])

    bob.find((o) => o.label === 'Set as Primary Contact').onClick()
    bob.find((o) => o.label === 'Delete').onClick()
    await flush()
    expect(S.calls.map((c) => [c.method.split('.').at(-1), c.args])).toEqual([
      ['set_primary_contact', { deal: 'DEAL-A', contact: 'bob@a' }],
      ['remove_contact', { deal: 'DEAL-A', contact: 'bob@a' }],
    ])
  })

  it("does not show the previous deal's contacts while the next one loads", async () => {
    await visit(MobileDeal, { dealId: 'DEAL-A' })
    page.unmount()

    S.delay.sections = 50
    S.delay.contacts = 100
    await visit(MobileDeal, { dealId: 'DEAL-B' })
    expect(contactsText()).not.toContain('Alice')
    await flush(150)
    expect(contactsText()).toContain('Carol OfB')
  })

  it('keeps the contacts when the layout reload lands after them', async () => {
    await visit(MobileDeal, { dealId: 'DEAL-A' })
    page.unmount()

    S.delay.sections = 100
    S.delay.contacts = 1
    await visit(MobileDeal, { dealId: 'DEAL-C' })
    await flush(150)
    expect(contactsText()).toContain('Dan OfC')
  })

  it('links the organization field to the organization', async () => {
    await visit(MobileDeal, { dealId: 'DEAL-A' })
    const organization = S.panels
      .at(-1)
      .sections[1].columns[0].fields.find((f) => f.fieldname === 'organization')
    expect(typeof organization.link).toBe('function')
    expect(typeof organization.create).toBe('function')
  })
})

describe.each([
  ['MobileDeal', MobileDeal, { dealId: 'DEAL-A' }],
  ['MobileLead', MobileLead, { leadId: 'LEAD-A' }],
])('%s on rotation', (name, Page, props) => {
  it('keeps the Details tab when the phone turns to landscape', async () => {
    isMobileView.value = true
    await visit(Page, props)
    expect(tabLabels()[0]).toBe('Details')

    isMobileView.value = false // wider than the breakpoint, page unchanged
    await flush()
    expect(tabLabels()[0]).toBe('Details')
    expect(page.el.querySelector('[data-section]')).not.toBeNull()
  })
})
