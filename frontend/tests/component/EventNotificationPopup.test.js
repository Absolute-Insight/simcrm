import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

/* A fresh copy of the composable's module state for each test. The alerts are
   kept by useStorage, and resetting modules does not reset localStorage: on
   Node 24 (CI) happy-dom's localStorage works, so an alert one test left
   behind -- hidden there only because that test had dismissed it -- came back
   in the next, and showed instead of the case's own. On Node 25+ Node's own
   global localStorage, undefined without --localstorage-file, shadows
   happy-dom's, useStorage falls back to memory, and the leak did not show. */
function clearStoredAlerts() {
  try {
    window.localStorage?.clear()
  } catch {
    // no usable storage: useStorage keeps the alerts in module memory instead
  }
}

beforeEach(() => {
  clearStoredAlerts()
  vi.resetModules()
  saved.length = 0
  storedSettings = Promise.resolve({ completedEvents: [] })
})

afterEach(() => {
  vi.useRealTimers()
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

  describe('when the event is', () => {
    const at = (when) => ({
      event_name: `EV-${when}`,
      starts_on: when,
      ends_on: dayjs(when).add(1, 'hour').format('YYYY-MM-DD HH:mm:ss'),
    })
    // every alert's time line, so one left over from another test fails loudly
    const timeLines = () =>
      [...document.body.querySelectorAll('.text-ink-gray-6')].map((el) =>
        el.textContent.trim(),
      )

    it.each([
      ['later today', at('2026-10-30 15:00:00'), '3:00 pm - 4:00 pm'],
      ['tomorrow', at('2026-10-31 09:00:00'), 'Tomorrow · 9:00 am - 10:00 am'],
      [
        'next week',
        at('2026-11-06 09:00:00'),
        'Fri, 6 Nov · 9:00 am - 10:00 am',
      ],
      [
        'next year',
        at('2027-01-05 09:00:00'),
        'Tue, 5 Jan 2027 · 9:00 am - 10:00 am',
      ],
      [
        'all day tomorrow',
        { ...at('2026-10-31 00:00:00'), all_day_event: 1 },
        'Tomorrow · All Day',
      ],
    ])('%s, it says which day', async (_, when, expected) => {
      vi.useFakeTimers({ toFake: ['Date'] })
      vi.setSystemTime(new Date(2026, 9, 30, 10, 0)) // Fri 30 Oct, 10:00
      const socketSide = await mountPopupAndSocketSide()

      socketSide.handleEventNotification(reminder(when))
      await flush()

      expect(timeLines()).toEqual([expected])
    })
  })
})
