import { h, reactive } from 'vue'
import { routeLocationKey, routerKey } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import { setConfig } from 'frappe-ui'
import Activities from '@/components/Activities/Activities.vue'

// Activities on frappe-ui's real createResource and createDocumentResource,
// a fake server and a fake socket. Children are stubs that count mounts.
const S = vi.hoisted(() => ({
  requests: [],
  mounts: {},
  socket: {},
  server: {},
  timeline: () => [[], [], [], [], []],
  slow: null,
  doc: null,
}))

vi.mock('@/data/document', async () => {
  const { createDocumentResource } = await import('frappe-ui')
  return {
    useDocument: (doctype, name) => ({
      document: (S.doc = createDocumentResource({ doctype, name })),
    }),
  }
})
vi.mock('@/stores/global', () => ({
  globalStore: () => ({
    $socket: {
      on: (event, fn) => (S.socket[event] = fn),
      off: () => {},
      emit: () => {},
    },
    $dialog: () => {},
  }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: (u) => ({ full_name: u }) }),
}))
vi.mock('@/composables/useTimelinePreferences', async () => {
  const { ref } = await import('vue')
  return {
    useTimelinePreferences: () => ({
      isNewestFirst: ref(false),
      showExactTimestamp: ref(false),
    }),
  }
})
vi.mock('@/composables/whatsapp', async () => {
  const { ref } = await import('vue')
  return { whatsappEnabled: ref(false) }
})
vi.mock('@/utils', () => ({ startCase: (s) => s }))

const { counted } = vi.hoisted(() => ({
  counted: (name) => ({
    default: {
      name,
      inheritAttrs: false,
      mounted() {
        S.mounts[name] = (S.mounts[name] || 0) + 1
      },
      render() {
        return null
      },
    },
  }),
}))
vi.mock('@/components/Activities/ActivityHeader.vue', () =>
  counted('ActivityHeader'),
)
vi.mock('@/components/Activities/EmailArea.vue', () => counted('EmailArea'))
vi.mock('@/components/Activities/CommentArea.vue', () => counted('CommentArea'))
vi.mock('@/components/Activities/CallArea.vue', () => counted('CallArea'))
vi.mock('@/components/Activities/NoteArea.vue', () => counted('NoteArea'))
vi.mock('@/components/Activities/TaskArea.vue', () => counted('TaskArea'))
vi.mock('@/components/Activities/AttachmentArea.vue', () =>
  counted('AttachmentArea'),
)
vi.mock('@/components/Activities/DataFields.vue', () => counted('DataFields'))
vi.mock('@/components/Activities/EventArea.vue', () => counted('EventArea'))
vi.mock('@/components/Activities/WhatsAppArea.vue', () =>
  counted('WhatsAppArea'),
)
vi.mock('@/components/Activities/WhatsAppBox.vue', () => counted('WhatsAppBox'))
vi.mock('@/components/Activities/AllModals.vue', () => counted('AllModals'))
vi.mock('@/components/Activities/TimelineTimestamp.vue', () =>
  counted('TimelineTimestamp'),
)
vi.mock('@/components/UserAvatar.vue', () => counted('UserAvatar'))
vi.mock('@/components/ListViews/EmptyState.vue', () => counted('EmptyState'))
vi.mock('@/components/Modals/WhatsappTemplateSelectorModal.vue', () =>
  counted('WATemplates'),
)
vi.mock('@/components/FilesUploader/FilesUploader.vue', () =>
  counted('FilesUploader'),
)
// The composer, kept so a test can say "the rep just sent something".
vi.mock('@/components/CommunicationArea.vue', () => ({
  default: {
    emits: ['scroll'],
    setup(_, { emit, expose }) {
      S.composer = { sent: () => emit('scroll') }
      expose({ show: false })
      return () => null
    },
  },
}))
vi.mock('@/components/FadedScrollableDiv.vue', () => ({
  default: {
    render() {
      return h('div', this.$slots.default?.())
    },
  },
}))

const tabs = [
  { name: 'Activity', value: 'activity' },
  { name: 'Emails', value: 'emails' },
  { name: 'Comments', value: 'comments' },
  { name: 'Data', value: 'data' },
  { name: 'Events', value: 'events' },
]

let deal = 0
const newDeal = () => `CRM-DEAL-2026-${String(++deal).padStart(5, '0')}`

function open(docname, tab, hash = '') {
  return mount(Activities, {
    props: { doctype: 'CRM Deal', docname, tabs, tabIndex: tab },
    plugins: [
      {
        install(app) {
          app.provide(routeLocationKey, reactive({ hash, name: 'Deal' }))
          app.provide(routerKey, { push: () => {} })
        },
      },
    ],
  })
}

const sent = (url) => S.requests.filter((r) => r === url).length
const spinner = (w) => w.el.textContent.includes('Loading...')

async function settle(ms = 0) {
  for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, ms))
}

beforeEach(() => {
  S.requests.length = 0
  S.mounts = {}
  S.socket = {}
  S.timeline = () => [[], [], [], [], []]
  S.slow = null
  setConfig('resourceFetcher', ({ url, params }) => {
    S.requests.push(url)
    if (url === 'frappe.client.get') {
      return Promise.resolve(JSON.parse(JSON.stringify(S.server)))
    }
    if (url === 'crm.api.activities.get_activities') {
      const data = S.timeline(params)
      return S.slow
        ? new Promise((r) => setTimeout(() => r(data), S.slow))
        : Promise.resolve(data)
    }
    return Promise.resolve(null)
  })
})

describe('Activities tabs', () => {
  it('shows the loaded timeline on the next tab while it refreshes', async () => {
    const name = newDeal()
    S.server = { doctype: 'CRM Deal', name }
    open(name, 'activity').unmount()
    await settle()

    // Tabs mounts a fresh Activities for the tab the rep clicks.
    S.slow = 50
    const emails = open(name, 'emails')
    expect(spinner(emails)).toBe(false)
    await settle(20)
    expect(sent('crm.api.activities.get_activities')).toBe(2)
  })

  it('shows a spinner on a first load', () => {
    S.slow = 50
    const w = open(newDeal(), 'activity')
    expect(spinner(w)).toBe(true)
  })

  it('opens the Data and Events tabs without loading the timeline', async () => {
    const name = newDeal()
    S.server = { doctype: 'CRM Deal', name }
    S.slow = 50
    const data = open(name, 'data')
    expect(S.mounts.DataFields).toBe(1)
    data.unmount()
    const events = open(name, 'events')
    expect(S.mounts.EventArea).toBe(1)
    events.unmount()
    await settle(20)
    expect(sent('crm.api.activities.get_activities')).toBe(0)
  })
})

describe('Activities realtime refresh', () => {
  it("keeps the rep's unsaved Data-tab edits when a colleague comments", async () => {
    const name = newDeal()
    S.server = {
      doctype: 'CRM Deal',
      name,
      probability: 10,
      communication_status: 'Open',
    }
    open(name, 'data')
    await settle()
    const doc = S.doc
    expect(doc.doc.probability).toBe(10)

    doc.doc.probability = 80 // typed, Save not pressed
    await settle()
    expect(doc.isDirty).toBe(true)

    // A colleague's email reply moves a field the server keeps itself.
    S.server = { ...S.server, communication_status: 'Replied' }
    S.socket.docinfo_update({
      doc: { reference_doctype: 'CRM Deal', reference_name: name },
      key: 'comments',
    })
    await settle()

    expect(sent('frappe.client.get')).toBe(2)
    expect(doc.doc.probability).toBe(80)
    expect(doc.doc.communication_status).toBe('Replied')
    expect(doc.isDirty).toBe(true)
    expect(S.mounts.DataFields).toBe(1)
  })
})

describe('Activities scroll position', () => {
  let scrolled
  let original
  beforeEach(async () => {
    // Let the 500 ms scroll timers of earlier tests run out first.
    await new Promise((r) => setTimeout(r, 600))
    scrolled = []
    original = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = function () {
      scrolled.push(this.id || 'newest')
    }
    return () => (Element.prototype.scrollIntoView = original)
  })

  const comments = () => [
    [1, 2, 3, 4, 5].map((i) => ({
      name: 'CMT-' + i,
      activity_type: 'comment',
      owner: 'rep@example.com',
      content: '<p>c' + i + '</p>',
      creation: `2026-10-2${i} 10:00:00`,
      attachments: [],
    })),
    [],
    [],
    [],
    [],
  ]

  it('stays on the comment a mention notification links to', async () => {
    S.timeline = comments
    S.slow = 100
    open(newDeal(), 'activity', '#CMT-3')
    await settle(400)
    expect(scrolled.length).toBeGreaterThan(0)
    expect(scrolled.at(-1)).toBe('CMT-3')
  })

  it('goes to the newest row once the rep has posted', async () => {
    S.timeline = comments
    const name = newDeal()
    open(name, 'activity', '#CMT-3')
    await settle(200)
    expect(scrolled.at(-1)).toBe('CMT-3')

    // The rep posts; the timeline reloads with their comment on it.
    S.composer.sent()
    S.socket.docinfo_update({
      doc: { reference_doctype: 'CRM Deal', reference_name: name },
      key: 'comments',
    })
    await settle(200)
    expect(scrolled.at(-1)).toBe('newest')
  })
})
