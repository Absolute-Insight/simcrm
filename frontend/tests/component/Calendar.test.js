import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'
import { setConfig } from 'frappe-ui'
import { mount } from './mount.js'
import CalendarPage from '@/pages/Calendar.vue'

/* pages/Calendar.vue with the real frappe-ui list resource behind a fake
   fetcher. The frappe-ui Calendar is a stand-in that, like the real one (a
   watch with immediate: true), reports its visible range while it sets up, and
   keeps the props it was given so a test can click a cell. */

const state = vi.hoisted(() => ({
  requests: [],
  calendar: null,
  panels: [],
  pickers: [],
  shortcuts: [],
}))

// A stand-in child that keeps the props it is given in `list`.
const recorder = vi.hoisted(() => (list) => async () => {
  const { h } = await import('vue')
  return {
    default: {
      inheritAttrs: false,
      setup(_, { attrs }) {
        list.push(attrs)
        return () => h('div')
      },
    },
  }
})

vi.mock('frappe-ui/experimental', async () => {
  const { h, ref } = await import('vue')
  return {
    CalendarActiveEvent: ref(''),
    Calendar: {
      name: 'Calendar',
      inheritAttrs: false,
      emits: ['rangeChange', 'create', 'update', 'delete'],
      setup(_, { attrs, emit, slots }) {
        state.calendar = attrs
        emit('rangeChange', {
          view: 'Week',
          startDate: '2026-10-25',
          endDate: '2026-10-31',
        })
        return () =>
          h('div', [
            slots.header?.({
              currentMonthYear: 'October 2026',
              activeView: 'Week',
              selectedMonthDate: new Date(2026, 9, 30),
              decrement: () => {},
              increment: () => {},
              updateActiveView: () => {},
              onMonthYearChange: () => {},
              setCalendarDate: () => {},
            }),
          ])
      },
    },
  }
})
vi.mock('frappe-ui', async (importOriginal) => {
  const { h } = await import('vue')
  const passThrough = {
    setup:
      (_, { slots }) =>
      () =>
        h('div', slots),
  }
  return {
    ...(await importOriginal()),
    DatePicker: passThrough,
    Tooltip: passThrough,
    usePageMeta: () => {},
  }
})
vi.mock('@/components/Calendar/CalendarEventPanel.vue', () =>
  recorder(state.panels)(),
)
vi.mock('@/components/Controls/Link.vue', () => recorder(state.pickers)())
vi.mock('@/components/LayoutHeader.vue', () => recorder([])())
vi.mock('@/components/ViewBreadcrumbs.vue', () => recorder([])())
vi.mock('@/components/ShortcutTooltip.vue', () => recorder([])())
vi.mock('@/composables/useKeyboardShortcuts', () => ({
  useKeyboardShortcuts: ({ shortcuts }) => state.shortcuts.push(...shortcuts),
}))
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: 'rep@example.com' }),
}))
vi.mock('@/stores/users', async () => {
  const { reactive } = await import('vue')
  const users = reactive({ data: { crmUsers: [{ name: 'rep@example.com' }] } })
  return {
    usersStore: () => ({
      users,
      getUser: (name) => ({ name, full_name: `Full(${name})` }),
    }),
  }
})
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog: () => {} }),
}))
vi.mock('@/stores/settings', async () => {
  const { ref } = await import('vue')
  return { getSettings: () => ({ settings: ref({}) }) }
})
vi.mock('@/composables/settings', async () => {
  const { ref } = await import('vue')
  return { isMobileView: ref(false) }
})
vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal()),
  useRoute: () => ({ query: {} }),
}))

const Stub = { render: () => h('div') }

async function open() {
  const w = mount(CalendarPage, {
    stubs: { Button: Stub, FormControl: Stub, UserAvatar: Stub },
  })
  await settle()
  return w
}

async function settle() {
  for (let i = 0; i < 4; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0))
    await nextTick()
  }
}

const eventLists = () =>
  state.requests.filter(
    (r) => r.url === 'frappe.client.get_list' && r.params.doctype === 'Event',
  )

beforeEach(() => {
  state.requests.length = 0
  state.panels.length = 0
  state.pickers.length = 0
  state.shortcuts.length = 0
  setConfig('resourceFetcher', async ({ url, params }) => {
    state.requests.push({ url, params: JSON.parse(JSON.stringify(params)) })
    return []
  })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('Calendar page', () => {
  it('asks only for the events in the visible range when it opens', async () => {
    await open()

    const lists = eventLists().map((r) => r.params.filters)
    expect(lists).toHaveLength(1)
    expect(lists[0]).toEqual(
      expect.arrayContaining([
        ['starts_on', '<=', '2026-10-31 23:59:59'],
        ['ends_on', '>=', '2026-10-25 00:00:00'],
      ]),
    )
  })

  it('lists an event once when it matches more than one participant row', async () => {
    const row = {
      name: 'EV-1',
      subject: 'Site visit',
      starts_on: '2026-10-30 09:00:00',
      ends_on: '2026-10-30 10:00:00',
      status: 'Open',
    }
    setConfig('resourceFetcher', async () => [
      row,
      row,
      { ...row, name: 'EV-2' },
    ])
    await open()

    const events = state.calendar.events.map((e) => e.id)
    expect(events).toEqual(['EV-1', 'EV-2'])
  })
})
