import { describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from './mount.js'

// Calendar page: creating an event with an attendee typed in by address.
// Audit FE-35: only the update path prepared such an attendee, so the insert
// carried reference_docname "new", which frappe's link check refuses. The
// event's save now gives each typed address its Contact (crm.api.attendees);
// the browser asks nothing and creates nothing.

const state = vi.hoisted(() => ({
  inserted: [],
  calls: [],
  calendar: null,
  panel: null,
}))

vi.mock('frappe-ui', async () => {
  const { defineComponent, h } = await import('vue')
  const dayjs = (await import('dayjs')).default
  const stub = defineComponent({ setup: () => () => h('div') })
  return {
    createListResource: () => ({
      data: [],
      update() {},
      reload: async () => [],
      insert: {
        loading: false,
        submit: (values) => state.inserted.push(values),
      },
      setValue: { loading: false, submit() {} },
    }),
    dayjs,
    DatePicker: stub,
    Tooltip: stub,
    toast: { success() {}, error() {} },
    usePageMeta() {},
    call: vi.fn(async (method, args) => {
      state.calls.push([method, args])
    }),
  }
})
vi.mock('frappe-ui/experimental', async () => {
  const { defineComponent, h, ref } = await import('vue')
  return {
    Calendar: defineComponent({
      props: ['onCellClick'],
      setup(props) {
        state.calendar = props
        return () => h('div')
      },
    }),
    CalendarActiveEvent: ref(''),
  }
})
vi.mock('@/components/Calendar/CalendarEventPanel.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      props: ['event', 'mode'],
      emits: ['save'],
      setup(props, { emit }) {
        state.panel = { props, emit }
        return () => h('div')
      },
    }),
  }
})
for (const path of [
  '@/components/LayoutHeader.vue',
  '@/components/ViewBreadcrumbs.vue',
  '@/components/ShortcutTooltip.vue',
  '@/components/Controls/Link.vue',
]) {
  vi.doMock(path, async () => {
    const { defineComponent, h } = await import('vue')
    return { default: defineComponent({ setup: () => () => h('div') }) }
  })
}
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: 'rep@mbp.test' }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    users: { data: { crmUsers: [] } },
    getUser: (u) => ({ full_name: u, user_image: '' }),
  }),
}))
vi.mock('@/stores/global', () => ({ globalStore: () => ({ $dialog() {} }) }))
vi.mock('@/stores/settings', async () => {
  const { ref } = await import('vue')
  return { getSettings: () => ({ settings: ref({}) }) }
})
vi.mock('@/composables/settings', async () => {
  const { ref } = await import('vue')
  return { isMobileView: ref(false) }
})
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))
vi.mock('@/utils/dialogs', () => ({ isDialogOpen: () => false }))

const { default: CalendarPage } = await import('@/pages/Calendar.vue')

const flush = async () => {
  for (let i = 0; i < 5; i++) {
    await nextTick()
    await new Promise((r) => setTimeout(r, 0))
  }
}

describe('Calendar: creating an event', () => {
  it('sends each typed attendee as its address, for the save to resolve', async () => {
    mount(CalendarPage, { stubs: { Button: { render: () => null } } })
    await flush()
    state.calendar.onCellClick({ date: '2026-10-30', time: '09:00' })
    await flush()
    expect(state.panel.props.mode).toBe('new')

    // what the panel saves for two addresses typed into Attendee
    state.panel.emit('save', {
      ...state.panel.props.event,
      title: 'Site meeting',
      event_participants: [
        {
          email: 'colleague@mbp.test',
          reference_doctype: 'Contact',
          reference_docname: 'new',
        },
        {
          email: 'known@client.test',
          reference_doctype: 'Contact',
          reference_docname: '',
        },
      ],
    })
    await flush()

    expect(state.inserted).toHaveLength(1)
    expect(state.inserted[0].event_participants).toEqual([
      {
        email: 'colleague@mbp.test',
        reference_doctype: 'Contact',
        reference_docname: '',
      },
      {
        email: 'known@client.test',
        reference_doctype: 'Contact',
        reference_docname: '',
      },
    ])
    // no lookup a rep's row scoping would answer, and no Contact from here
    expect(state.calls).toEqual([])
  })
})
