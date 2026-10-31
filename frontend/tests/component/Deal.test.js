import {
  defineComponent,
  h,
  nextTick,
  onBeforeUnmount,
  reactive,
  ref,
} from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

/**
 * The desktop Deal and Lead pages, mounted per record the way the router does
 * it, over frappe-ui's real resource cache and real Tabs, with the real
 * Activities in each tab panel. v1 Tabs mounts a panel per tab, so switching
 * tabs unmounts one Activities and mounts another. Everything else the pages
 * render is a recorder: the tests read what the page hands it.
 */

const S = vi.hoisted(() => ({
  refused: null,
  docs: {},
  calls: [],
  dialled: [],
  composers: [],
  children: {},
  server: { contacts: {} },
  fetches: {},
  route: null,
}))

vi.mock('frappe-ui', async (importOriginal) => {
  const real = await importOriginal()
  const { defineComponent, h } = await import('vue')
  // Records the props a widget was given and renders its default slot.
  const recorder = (name, slotProps = {}) =>
    defineComponent({
      name,
      inheritAttrs: false,
      setup(_, { attrs, slots }) {
        return () => {
          ;(S.children[name] ||= []).push({ ...attrs })
          return h('div', { 'data-stub': name }, slots.default?.(slotProps))
        }
      },
    })
  return {
    ...real,
    call: vi.fn(async (method, args) => {
      S.calls.push({ method, args })
      return true
    }),
    toast: { success() {}, error() {}, create() {} },
    Breadcrumbs: recorder('Breadcrumbs'),
    Dropdown: recorder('Dropdown', { open: false }),
    Tooltip: recorder('Tooltip'),
    Avatar: recorder('Avatar'),
    FileUploader: recorder('FileUploader', {
      openFileSelector() {},
      error: '',
    }),
  }
})

const blank = (name) => ({
  default: defineComponent({ name, render: () => null }),
})
const slotted = (name) => ({
  default: defineComponent({
    name,
    setup:
      (_, { slots }) =>
      () =>
        h(
          'div',
          Object.values(slots).map((slot) => slot()),
        ),
  }),
})
for (const name of [
  'DeleteLinkedDocModal',
  'Icon',
  'AssignTo',
  'SLASection',
  'RecordSuggestions',
  'CustomActions',
  'EnrichFromWebsite',
  'SidePanelLayout',
  'CollapsibleSection',
  'UserAvatar',
  'Modals/OrganizationModal',
  'Modals/LostReasonModal',
  'Modals/ContactModal',
  'Modals/ConvertToDealModal',
  'Modals/WhatsappTemplateSelectorModal',
  'Controls/Link',
  'ListViews/EmptyState',
  'Activities/ActivityHeader',
  'Activities/EmailArea',
  'Activities/CommentArea',
  'Activities/CallArea',
  'Activities/NoteArea',
  'Activities/TaskArea',
  'Activities/AttachmentArea',
  'Activities/EventArea',
  'Activities/WhatsAppArea',
  'Activities/WhatsAppBox',
  'Activities/TimelineTimestamp',
  'Activities/DataFields',
  'Activities/AllModals',
]) {
  vi.doMock(`@/components/${name}.vue`, () => blank(name))
}
for (const name of ['LayoutHeader', 'Resizer', 'FadedScrollableDiv']) {
  vi.doMock(`@/components/${name}.vue`, () => slotted(name))
}
vi.mock('@/components/ErrorPage.vue', () => ({
  default: defineComponent({
    name: 'ErrorPage',
    inheritAttrs: false,
    setup(_, { attrs }) {
      return () => {
        ;(S.children.ErrorPage ||= []).push({ ...attrs })
        return null
      }
    },
  }),
}))
vi.mock('@/components/FilesUploader/FilesUploader.vue', () => ({
  default: defineComponent({
    name: 'FilesUploader',
    inheritAttrs: false,
    setup(_, { attrs }) {
      return () => {
        ;(S.children.FilesUploader ||= []).push({ ...attrs })
        return null
      }
    },
  }),
}))
// The composer each Activities panel renders under the Activity, Emails and
// Comments tabs; `show` is what CommunicationArea exposes for the email box.
vi.mock('@/components/CommunicationArea.vue', () => ({
  default: defineComponent({
    name: 'CommunicationArea',
    setup(_, { expose }) {
      const composer = { show: ref(false), live: true }
      S.composers.push(composer)
      onBeforeUnmount(() => (composer.live = false))
      expose({ show: composer.show })
      return () => h('div', composer.show.value ? 'composer open' : '')
    },
  }),
}))

vi.mock('@/data/document', () => ({
  useDocument: (doctype, name) => {
    S.docs[name] ||= reactive({
      doc: S.refused ? null : { name, doctype, ...seed(doctype, name) },
      save: { submit: vi.fn() },
      reload: vi.fn(),
    })
    return {
      document: S.docs[name],
      assignees: { data: [], reload() {} },
      permissions: { data: {} },
      scripts: { data: [] },
      error: ref(S.refused || ''),
      triggerOnChange: async () => {},
      triggerOnRender: async () => {},
    }
  },
}))
function seed(doctype, name) {
  if (doctype === 'CRM Organization')
    return { organization_logo: `/files/${name}.png` }
  return {
    status: doctype === 'CRM Deal' ? 'Qualification' : 'New',
    email: 'buyer@acme.co.za',
    organization: 'Acme Steel',
  }
}
vi.mock('@/stores/settings', () => ({ getSettings: () => ({ brand: {} }) }))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({
    $dialog() {},
    $socket: { on() {}, off() {}, emit() {} },
    makeCall: (number) => S.dialled.push(number),
  }),
}))
vi.mock('@/stores/statuses', () => ({
  statusesStore: () => ({
    statusOptions: () => [{ label: 'Won' }],
    getDealStatus: () => ({ type: 'Open', color: '' }),
    getLeadStatus: () => ({ type: 'Open', color: '' }),
  }),
}))
vi.mock('@/stores/meta', () => ({
  getMeta: () => ({ doctypeMeta: ref({ title_field: 'organization' }) }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: (u) => ({ full_name: u }) }),
}))
vi.mock('@/composables/whatsapp', () => ({ whatsappEnabled: ref(false) }))
vi.mock('@/composables/telephony', () => ({ callEnabled: ref(true) }))
vi.mock('@/composables/useBroadcast', () => ({
  useBroadcast: () => ({ on() {}, send() {} }),
}))
vi.mock('@/composables/useUnsavedChangesWarning', () => ({
  useUnsavedChangesWarning() {},
}))
vi.mock('@/composables/useTimelinePreferences', () => ({
  useTimelinePreferences: () => ({
    isNewestFirst: ref(false),
    showExactTimestamp: ref(false),
  }),
}))
vi.mock('@/utils', () => ({
  openWebsite() {},
  setupCustomizations: async () => ({}),
  copyToClipboard() {},
  isTranslatable: () => false,
  validateIsImageFile: () => true,
  startCase: (s) => s,
}))
vi.mock('@/utils/view', () => ({ getView: () => null }))
// A stand-in route the page can be mounted over directly, unless a test
// installs a real router (S.router), which then answers instead.
vi.mock('vue-router', async (importOriginal) => {
  const { reactive } = await import('vue')
  const real = await importOriginal()
  S.route = reactive({ hash: '', query: {}, params: {} })
  return {
    ...real,
    useRoute: () => (S.router ? real.useRoute() : S.route),
    useRouter: () =>
      S.router
        ? real.useRouter()
        : { push: (to) => (S.route.hash = to.hash || '') },
  }
})

const { createRouter, createMemoryHistory, RouterView } = await import(
  'vue-router'
)
const { setConfig } = await import('frappe-ui')
const Deal = (await import('@/pages/Deal.vue')).default
const Lead = (await import('@/pages/Lead.vue')).default

setConfig('resourceFetcher', async ({ url, params }) => {
  S.fetches[url] = (S.fetches[url] || 0) + 1
  if (url.endsWith('get_deal_contacts') && S.refused) throw S.refused
  if (url.endsWith('get_deal_contacts'))
    return structuredClone(S.server.contacts[params.name] || [])
  if (url.endsWith('get_activities')) return [[], [], [], [], []]
  return []
})

async function flush() {
  for (let i = 0; i < 10; i++) {
    await new Promise((r) => setTimeout(r))
    await nextTick()
  }
}

const stubs = {
  Badge: { render: () => null },
  ErrorMessage: { render: () => null },
  Button: defineComponent({
    inheritAttrs: false,
    setup:
      (_, { attrs }) =>
      () =>
        h('button', {
          'data-tooltip': attrs.tooltip,
          'data-label': attrs.label,
          onClick: attrs.onClick,
        }),
  }),
}

let page
async function visit(Page, props) {
  S.children = {}
  page = mount(Page, { props, stubs })
  await flush()
}

// The app's own wiring: App.vue keys <router-view> on the full path, which
// carries the tab's hash, so a tab change remounts the whole record page.
async function visitRouted(path) {
  S.children = {}
  S.router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/deals/:dealId', name: 'Deal', component: Deal, props: true },
      { path: '/leads/:leadId', name: 'Lead', component: Lead, props: true },
    ],
  })
  await S.router.push(path)
  const App = defineComponent({
    render: () => h(RouterView, { key: S.router.currentRoute.value.fullPath }),
  })
  page = mount(App, { stubs, plugins: [S.router] })
  await flush()
}

const button = (tooltip) =>
  page.el.querySelector(`button[data-tooltip="${tooltip}"]`)
const activeTab = () =>
  page.el.querySelector('[role="tab"][data-state="active"]')?.textContent.trim()

async function openTab(label) {
  const trigger = [...page.el.querySelectorAll('[role="tab"]')].find(
    (t) => t.textContent.trim() === label,
  )
  trigger.dispatchEvent(new MouseEvent('mousedown', { button: 0 }))
  await flush()
}

afterEach(() => {
  page?.unmount()
  S.docs = {}
  S.calls.length = 0
  S.dialled.length = 0
  S.composers.length = 0
  S.route.hash = ''
  S.router = null
  S.refused = null
})

describe.each([
  ['Deal', Deal, { dealId: 'CRM-DEAL-1' }, '/deals/CRM-DEAL-1'],
  ['Lead', Lead, { leadId: 'CRM-LEAD-1' }, '/leads/CRM-LEAD-1'],
])('%s', (name, Page, props, path) => {
  it('tells a refused rep so, in words', async () => {
    S.refused = {
      exc_type: 'PermissionError',
      messages: ['Not allowed via controller permission check'],
    }
    await visit(Page, props)
    const shown = S.children.ErrorPage.at(-1)
    expect(shown.errorTitle).toBe('No access')
    expect(shown.errorMessage).toMatch(/do not have access to this record/)
  })

  it('offers the status dropdown without a form script', async () => {
    await visit(Page, props)
    const header = S.children.Dropdown?.find((d) => d.align === 'end')
    expect(header?.options).toEqual([{ label: 'Won' }])
  })

  it.each(['Data', 'Notes'])(
    '"Send an Email" from the %s tab opens the composer on the Emails tab',
    async (start) => {
      await visitRouted(`${path}#${start.toLowerCase()}`)
      const before = page.el.firstElementChild
      button('Send an Email').click()
      await flush()
      expect(S.router.currentRoute.value.hash).toBe('#emails')
      expect(page.el.firstElementChild).not.toBe(before) // remounted
      expect(activeTab()).toBe('Emails')
      const live = S.composers.filter((c) => c.live)
      expect(live.map((c) => c.show.value)).toEqual([true])
    },
  )

  it('opens the composer for that one tab change, not a later visit', async () => {
    await visitRouted(`${path}#data`)
    button('Send an Email').click()
    await flush()
    await S.router.push(`${path}#data`)
    await flush()
    await S.router.push(`${path}#emails`)
    await flush()
    expect(activeTab()).toBe('Emails')
    const live = S.composers.filter((c) => c.live)
    expect(live.map((c) => c.show.value)).toEqual([false])
  })

  it.each(['Data', 'Notes'])(
    '"Send an Email" from the %s tab still opens it when the page is not remounted',
    async (start) => {
      await visit(Page, props)
      await openTab(start)
      button('Send an Email').click()
      await flush()
      expect(activeTab()).toBe('Emails')
      const live = S.composers.filter((c) => c.live)
      expect(live.map((c) => c.show.value)).toEqual([true])
    },
  )

  it.each(['Activity', 'Emails', 'Comments'])(
    '"Send an Email" on the %s tab opens the composer that is already there',
    async (start) => {
      await visit(Page, props)
      await openTab(start)
      button('Send an Email').click()
      await flush()
      expect(activeTab()).toBe(start)
      const live = S.composers.filter((c) => c.live)
      expect(live.map((c) => c.show.value)).toEqual([true])
    },
  )

  it('switches to Attachments after a file is attached from the header', async () => {
    await visit(Page, props)
    S.children.FilesUploader.at(-1).onAfter()
    await flush()
    expect(activeTab()).toBe('Attachments')
  })
})

describe('Deal', () => {
  it('leaves no rejection unhandled when its contacts are refused', async () => {
    const rejections = []
    const onRejection = (reason) => rejections.push(reason)
    process.on('unhandledRejection', onRejection)
    S.refused = Object.assign(new Error('refused'), {
      exc_type: 'PermissionError',
    })
    await visit(Deal, { dealId: 'CRM-DEAL-REFUSED' })
    await new Promise((r) => setTimeout(r, 20))
    process.off('unhandledRejection', onRejection)
    expect(rejections).toEqual([])
  })

  it("dials the contact's current number after a revisit", async () => {
    const contact = (mobile_no) => [
      { name: 'CONT-1', full_name: 'Thabo M', is_primary: 1, mobile_no },
    ]
    S.server.contacts['CRM-DEAL-2'] = contact('+27 82 000 0001')
    await visit(Deal, { dealId: 'CRM-DEAL-2' })
    page.unmount() // View Contact, where the rep changes the mobile number...

    S.server.contacts['CRM-DEAL-2'] = contact('+27 82 999 9999')
    await visit(Deal, { dealId: 'CRM-DEAL-2' }) // ...and back to the deal
    button('Make a Call').click()
    expect(S.dialled).toEqual(['+27 82 999 9999'])
  })

  it("shows the new organization's logo and name once it changes", async () => {
    await visit(Deal, { dealId: 'CRM-DEAL-3' })
    const header = () => ({
      name: S.children.Tooltip.findLast(
        (t) => t.text && t.text !== 'Organization Logo',
      ).text,
      logo: S.children.Avatar.at(-1).image,
    })
    expect(header()).toEqual({
      name: 'Acme Steel',
      logo: '/files/Acme Steel.png',
    })

    S.docs['CRM-DEAL-3'].doc.organization = 'Bravo Mining' // side panel edit
    await flush()
    expect(header()).toEqual({
      name: 'Bravo Mining',
      logo: '/files/Bravo Mining.png',
    })

    S.docs['CRM-DEAL-3'].doc.organization = '' // and cleared
    await flush()
    expect(header()).toEqual({ name: 'Set an Organization', logo: undefined })
  })
})
