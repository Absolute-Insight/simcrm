import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'
import { dayjs } from 'frappe-ui'
import { mount } from './mount.js'

/* App.vue mounts the reminder popup, and Notifications.vue (the sidebar panel)
   receives the `event_notification` socket payloads. Both call
   useEventNotificationAlert(); this mounts the real popup and the real
   composable, with a stand-in that does what Notifications.vue does with a
   payload. */

const saved = []
let storedSettings
vi.mock('@/data/userSettings', () => ({
  getUserSettings: () => storedSettings,
  useUserSettings: () => ({ save: async (...args) => saved.push(args[2]) }),
}))
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: 'rep@example.com' }),
}))
vi.mock('@/composables/event', () => ({ useEvent: () => ({}) }))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: (name) => ({ full_name: name }) }),
}))
vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal()),
  useRouter: () => ({ push: () => {} }),
}))

// Both registered globally in main.js.
const CalendarIcon = { render: () => h('i') }
const MultipleAvatar = { render: () => h('span') }

async function mountPopupAndSocketSide() {
  const { default: EventNotificationPopup } = await import(
    '@/components/EventNotificationPopup.vue'
  )
  const { useEventNotificationAlert } = await import('@/data/notifications')
  let socketSide
  const NotificationsStandIn = {
    setup() {
      socketSide = useEventNotificationAlert()
      return () => null
    },
  }
  mount(
    { render: () => [h(EventNotificationPopup), h(NotificationsStandIn)] },
    { stubs: { CalendarIcon, MultipleAvatar } },
  )
  await flush()
  return socketSide
}

async function flush() {
  for (let i = 0; i < 5; i++) {
    await Promise.resolve()
    await nextTick()
  }
}

const reminder = (overrides) => {
  const start = dayjs().add(10, 'minute')
  return {
    event_name: 'EV-2026-0001',
    subject: 'Site visit: pump station',
    starts_on: start.format('YYYY-MM-DD HH:mm:ss'),
    ends_on: start.add(1, 'hour').format('YYYY-MM-DD HH:mm:ss'),
    all_day_event: 0,
    event_participants: [],
    owner: 'rep@example.com',
    ...overrides,
  }
}

const popupText = () => document.body.textContent

// A fresh copy of the composable's module state for each test. (The test
// environment exposes no localStorage, so useStorage keeps alerts in memory.)
beforeEach(() => {
  vi.resetModules()
  saved.length = 0
  storedSettings = Promise.resolve({ completedEvents: [] })
})

describe('event reminder popup', () => {
  it('keeps a dismissed reminder dismissed when the next tick re-sends it', async () => {
    const socketSide = await mountPopupAndSocketSide()
    const payload = reminder()

    socketSide.handleEventNotification(payload)
    await flush()
    expect(popupText()).toContain(payload.subject)

    document.body.querySelector('button').click()
    await new Promise((resolve) => setTimeout(resolve, 350))
    await flush()
    expect(popupText()).not.toContain(payload.subject)
    expect(saved.at(-1).completedEvents).toEqual([payload.event_name])

    // the next scheduler tick, same event, still inside its window
    socketSide.handleEventNotification(payload)
    await flush()
    expect(popupText()).not.toContain(payload.subject)
  })

  it('hides a reminder dismissed before a reload once the list has loaded', async () => {
    let load
    storedSettings = new Promise((resolve) => (load = resolve))
    const socketSide = await mountPopupAndSocketSide()
    const payload = reminder()

    // the re-send beats the stored dismissals in after a page reload
    socketSide.handleEventNotification(payload)
    await flush()
    load({ completedEvents: [payload.event_name] })
    await flush()

    expect(popupText()).not.toContain(payload.subject)
  })
})
