import { describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from './mount.js'

// Calendar page: creating an event with an attendee typed in by address.
// Audit FE-35: only the update path gave such an attendee a Contact, so the
// insert carried reference_docname "new" and the server refused the event.

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
      if (method === 'frappe.client.get_value') {
        // one of the two addresses already has a Contact
        return args.filters.email_id === 'known@client.test'
          ? { name: 'C-KNOWN' }
          : undefined
      }
      if (method === 'frappe.client.insert') return { name: 'C-NEW' }
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
  it('gives each typed attendee a Contact before the insert', async () => {
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
        reference_docname: 'C-NEW',
      },
      {
        email: 'known@client.test',
        reference_doctype: 'Contact',
        reference_docname: 'C-KNOWN',
      },
    ])
    // an existing Contact is used, not duplicated
    const created = state.calls.filter(([m]) => m === 'frappe.client.insert')
    expect(created.map(([, a]) => a.doc.email_ids[0].email_id)).toEqual([
      'colleague@mbp.test',
    ])
  })
})
