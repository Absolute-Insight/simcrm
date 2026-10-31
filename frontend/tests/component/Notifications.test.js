import { describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { mount } from './mount.js'
import Notifications from '@/components/Notifications.vue'

const { inbox } = await vi.hoisted(async () => {
  const { reactive } = await import('vue')
  return { inbox: reactive({ data: [], error: null, reload: () => {} }) }
})

vi.mock('@/stores/notifications', async () => ({
  visible: (await import('vue')).ref(true),
  notifications: inbox,
  notificationsStore: () => ({
    mark_as_read: { reload: () => {} },
    mark_doc_as_read: () => {},
    toggle: () => {},
  }),
}))
vi.mock('@/data/notifications', () => ({
  useEventNotificationAlert: () => ({ handleEventNotification: () => {} }),
}))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $socket: { on: () => {}, off: () => {} } }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: (name) => ({ full_name: name }) }),
}))

// Shaped as crm.api.notifications.get_notifications builds a row.
const row = (overrides) => ({
  creation: '2026-10-30 09:00:00.000000',
  from_user: { name: 'manager@example.com', full_name: 'Sales Manager' },
  type: 'Mention',
  to_user: 'rep@example.com',
  read: 0,
  hash: '#c0ffee',
  notification_text: '<div>Sales Manager mentioned you in a deal</div>',
  notification_type_doctype: 'Comment',
  notification_type_doc: 'c0ffee',
  reference_doctype: 'deal',
  reference_name: 'CRM-DEAL-2026-00001',
  route_name: 'Deal',
  ...overrides,
})

const standaloneTask = row({
  type: 'Assignment',
  hash: '#tasks',
  notification_text: '<div>Sales Manager assigned you a task: Call back</div>',
  notification_type_doctype: 'CRM Task',
  notification_type_doc: 'TASK-2026-00009',
  reference_doctype: 'lead',
  reference_name: null,
  route_name: null,
})

const Page = { render: () => null }
const Button = { render: () => h('button') }

// Vue rethrows a render error only in dev and replaces the row with a comment
// node; collect it so the test says what went wrong.
const collectErrors = (errors) => ({
  install(app) {
    app.config.errorHandler = (error) => errors.push(error)
  },
})

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: Page },
      { path: '/leads/:leadId', name: 'Lead', component: Page },
      { path: '/deals/:dealId', name: 'Deal', component: Page },
      { path: '/tasks/view/:viewType?', name: 'Tasks', component: Page },
    ],
  })
}

describe('Notifications panel', () => {
  // null is what the server sends now; 'Lead' is what it sent before, and is
  // the one that made vue-router throw "Missing required param leadId".
  it.each([null, 'Lead'])(
    'renders a task assigned with no lead or deal, linking to Tasks (route_name %s)',
    async (routeName) => {
      inbox.data = [row({}), { ...standaloneTask, route_name: routeName }]
      const errors = []
      const w = mount(Notifications, {
        plugins: [makeRouter(), collectErrors(errors)],
        stubs: { Button },
      })
      await nextTick()

      expect(errors.map(String)).toEqual([])
      const links = [...w.el.querySelectorAll('a')].map((a) => [
        a.getAttribute('href'),
        a.textContent.trim(),
      ])
      expect(links).toEqual([
        ['/deals/CRM-DEAL-2026-00001#c0ffee', expect.stringContaining('deal')],
        ['/tasks/view', expect.stringContaining('Call back')],
      ])
    },
  )

  it('renders a notification that names no record as a plain row', async () => {
    inbox.data = [
      row({ type: 'WhatsApp', reference_name: null, route_name: null }),
    ]
    const w = mount(Notifications, {
      plugins: [makeRouter()],
      stubs: { Button },
    })
    await nextTick()

    expect(w.el.querySelectorAll('a')).toHaveLength(0)
    expect(w.el.textContent).toContain('mentioned you in a deal')
  })
})
