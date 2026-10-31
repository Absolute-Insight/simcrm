import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, reactive } from 'vue'
import { mount } from './mount.js'

// The Calendar page's event panel, with only its leaf widgets stubbed.
// Audit FE-02, FE-37, FE-38, FE-89, FE-92.

const state = vi.hoisted(() => ({
  user: 'rep@mbp.test',
  server: {},
  gets: 0,
  dialogs: [],
  attendees: [],
  tabs: [],
  titles: [],
}))

vi.mock('frappe-ui', async () => {
  const { defineComponent, h } = await import('vue')
  const dayjs = (await import('dayjs')).default
  // keeps every live instance so a test can drive its emits
  const tracked = (name, list) =>
    defineComponent({
      name,
      inheritAttrs: false,
      props: ['modelValue', 'buttons', 'message', 'label'],
      emits: ['update:modelValue', 'change'],
      setup(props, { emit, slots }) {
        list?.push({ props, emit })
        return () =>
          h('div', { 'data-stub': name }, [
            props.message ? String(props.message) : null,
            slots.default?.(),
          ])
      },
    })
  return {
    TextInput: tracked('TextInput', state.titles),
    Switch: tracked('Switch'),
    DatePicker: tracked('DatePicker'),
    TimePicker: tracked('TimePicker'),
    ErrorMessage: tracked('ErrorMessage'),
    Dropdown: tracked('Dropdown'),
    TabButtons: tracked('TabButtons', state.tabs),
    Tooltip: tracked('Tooltip'),
    KeyboardShortcut: tracked('KeyboardShortcut'),
    dayjs,
    toast: { success() {}, error() {} },
    call: vi.fn(async (method, args) => {
      if (method === 'frappe.client.get') {
        state.gets++
        return JSON.parse(JSON.stringify(state.server[args.name]))
      }
      return {}
    }),
  }
})
vi.mock('frappe-ui/experimental', async () => {
  const { defineComponent, h, ref } = await import('vue')
  return {
    TextEditor: defineComponent({ setup: () => () => h('div') }),
    CalendarColorMap: { green: { color: '#30A66D' } },
    CalendarActiveEvent: ref(''),
  }
})
vi.mock('@/components/Calendar/Attendee.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      props: ['modelValue'],
      emits: ['update:modelValue'],
      setup(props, { emit }) {
        state.attendees.push({ props, emit })
        return () => h('div', { 'data-stub': 'Attendee' })
      },
    }),
  }
})
vi.mock('@/components/Controls/Link.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return { default: defineComponent({ setup: () => () => h('div') }) }
})
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: state.user }),
}))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog: (options) => state.dialogs.push(options) }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: (u) => ({ full_name: u, user_image: '' }) }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push() {} }) }))
vi.mock('@/utils/dialogs', () => ({ isDialogOpen: () => false }))

const { default: CalendarEventPanel } = await import(
  '@/components/Calendar/CalendarEventPanel.vue'
)

const passthrough = (name) =>
  defineComponent({
    name,
    inheritAttrs: false,
    props: ['label', 'disabled', 'loading'],
    emits: ['click'],
    setup(props, { slots, emit }) {
      return () =>
        h(
          name === 'Button' ? 'button' : 'div',
          { 'data-stub': name, onClick: (e) => emit('click', e) },
          [props.label, slots.prefix?.(), slots.default?.()],
        )
    },
  })

const flush = async (n = 5) => {
  for (let i = 0; i < n; i++) {
    await nextTick()
    await new Promise((r) => setTimeout(r, 0))
  }
}

function doc(name, extra = {}) {
  return {
    doctype: 'Event',
    name,
    subject: 'Visit: Impala Springs',
    description: '',
    status: 'Open',
    starts_on: '2026-10-30 09:00:00',
    ends_on: '2026-10-30 10:00:00',
    all_day: 0,
    event_type: 'Private',
    color: '#30A66D',
    attending: '',
    owner: 'rep@mbp.test',
    event_participants: [],
    notifications: [],
    ...extra,
  }
}

/** The panel as Calendar.vue renders it: props a test can change later. */
function panel(initial) {
  const props = reactive({ modelValue: true, ...initial })
  const emitted = { save: [], sync: [], edit: [] }
  const Host = defineComponent({
    setup: () => () =>
      h(CalendarEventPanel, {
        ...props,
        onSave: (e) => emitted.save.push(JSON.parse(JSON.stringify(e))),
        onSync: (id, e) => {
          emitted.sync.push([id, e])
          props.onSync?.(id, e)
        },
        onEdit: (e) => emitted.edit.push(e),
      }),
  })
  const w = mount(Host, {
    stubs: {
      Button: passthrough('Button'),
      FormControl: passthrough('FormControl'),
      UserAvatar: passthrough('UserAvatar'),
      CollapsibleSection: passthrough('CollapsibleSection'),
    },
    plugins: [
      {
        install: (app) =>
          app.provide('events', {
            setValue: { loading: false },
            insert: { loading: false },
          }),
      },
    ],
  })
  return { ...w, props, emitted }
}

beforeEach(() => {
  state.user = 'rep@mbp.test'
  state.server = {}
  state.gets = 0
  state.dialogs.length = 0
  state.attendees.length = 0
  state.tabs.length = 0
  state.titles.length = 0
})

describe('CalendarEventPanel: editing attendees (FE-02)', () => {
  it("keeps a visit's CRM Organization row and everyone's RSVP", async () => {
    state.server['EV-VISIT'] = doc('EV-VISIT', {
      event_participants: [
        {
          name: 'p-org',
          reference_doctype: 'CRM Organization',
          reference_docname: 'Impala Springs',
          email: null,
          attending: '',
        },
        {
          name: 'p-buyer',
          reference_doctype: 'Contact',
          reference_docname: 'C-0001',
          email: 'buyer@client.test',
          attending: 'Yes',
        },
      ],
    })
    const p = panel({ event: { id: 'EV-VISIT' }, mode: 'edit' })
    await flush()
    const attendee = state.attendees.at(-1)
    expect(attendee.props.modelValue).toHaveLength(2)
    // what Attendee emits for a typed address: the rows it was given, plus one
    attendee.emit('update:modelValue', [
      ...attendee.props.modelValue,
      { email: 'new@client.test', reference_docname: 'new' },
    ])
    await flush()
    ;[...p.el.querySelectorAll('button')]
      .find((b) => b.textContent.trim() === 'Save')
      .click()
    await flush()

    expect(p.emitted.save[0].event_participants).toEqual([
      {
        name: 'p-org',
        email: '',
        reference_doctype: 'CRM Organization',
        reference_docname: 'Impala Springs',
      },
      {
        name: 'p-buyer',
        email: 'buyer@client.test',
        reference_doctype: 'Contact',
        reference_docname: 'C-0001',
        attending: 'Yes',
      },
      {
        email: 'new@client.test',
        reference_doctype: 'Contact',
        reference_docname: 'new',
      },
    ])
  })
})

describe('CalendarEventPanel: opening an event (FE-37)', () => {
  it('shows the event as it is now, not as it was when first opened', async () => {
    state.server['EV-3'] = doc('EV-3')
    const first = panel({ event: { id: 'EV-3' }, mode: 'details' })
    await flush()
    expect(state.gets).toBe(1) // one GET for one open
    expect(first.el.textContent).toContain('9 - 10 am')
    first.unmount() // Esc: Calendar.vue unmounts the panel

    // dragged to the afternoon while the panel was closed
    state.server['EV-3'] = doc('EV-3', {
      starts_on: '2026-10-30 14:00:00',
      ends_on: '2026-10-30 15:00:00',
    })
    const second = panel({ event: { id: 'EV-3' }, mode: 'details' })
    await flush()
    expect(second.el.textContent).toContain('2 - 3 pm')
    expect(second.el.textContent).not.toContain('9 - 10 am')
  })

  it('switching details to edit keeps what is on screen', async () => {
    state.server['EV-4'] = doc('EV-4')
    const p = panel({ event: { id: 'EV-4' }, mode: 'details' })
    await flush()
    p.props.event = { id: 'EV-4' }
    p.props.mode = 'edit'
    await flush()
    expect(state.gets).toBe(1)
  })

  it('shows the event opened last when an earlier load answers later', async () => {
    state.server['EV-A'] = doc('EV-A', { subject: 'First' })
    state.server['EV-B'] = doc('EV-B', { subject: 'Second' })
    const { call } = await import('frappe-ui')
    let releaseA
    call.mockImplementationOnce(
      (_, args) =>
        new Promise((resolve) => {
          releaseA = () => resolve(doc(args.name, { subject: 'First' }))
        }),
    )
    const p = panel({ event: { id: 'EV-A' }, mode: 'details' })
    await flush()
    p.props.event = { id: 'EV-B' }
    await flush()
    releaseA()
    await flush()
    expect(p.el.textContent).toContain('Second')
    expect(p.el.textContent).not.toContain('First')
  })
})

describe('CalendarEventPanel: opening another event mid-edit (FE-38)', () => {
  it('puts the saved version back on the grid entry', async () => {
    state.server['EV-A'] = doc('EV-A', { subject: 'Site visit' })
    state.server['EV-B'] = doc('EV-B', { subject: 'Other' })
    // Calendar.vue's events.data and its syncEvent()
    const grid = [
      { id: 'EV-A', title: 'Site visit' },
      { id: 'EV-B', title: 'Other' },
    ]
    const onSync = (id, e) => {
      const target = grid.find((event) => event.id === id)
      if (target) Object.assign(target, e)
    }
    const p = panel({ event: { id: 'EV-A' }, mode: 'edit', onSync })
    await flush()
    const title = state.titles[0]
    title.emit('update:modelValue', 'Site visit MOVED TO FRIDAY')
    title.emit('change')
    await flush()
    expect(grid[0].title).toBe('Site visit MOVED TO FRIDAY') // live preview

    // event B clicked on the grid: Calendar.vue openEvent(e, 'details')
    p.props.event = { id: 'EV-B' }
    p.props.mode = 'details'
    await flush()
    expect(grid[0].title).toBe('Site visit')
    expect(p.el.textContent).toContain('Other')
  })
})

describe('CalendarEventPanel: Going? (FE-89)', () => {
  const publicEvent = () =>
    doc('EV-PUB', {
      event_type: 'Public',
      event_participants: [
        {
          name: 'p1',
          reference_doctype: 'Contact',
          reference_docname: 'C-1',
          email: 'buyer@client.test',
          attending: '',
        },
      ],
    })

  it('is not offered to a viewer who neither owns nor attends the event', async () => {
    state.user = 'manager@mbp.test'
    state.server['EV-PUB'] = publicEvent()
    const p = panel({ event: { id: 'EV-PUB' }, mode: 'details' })
    await flush()
    expect(p.el.textContent).not.toContain('Going?')
    expect(state.tabs).toHaveLength(0)
  })

  it('is offered to an attendee, and records their answer', async () => {
    state.user = 'buyer@client.test'
    state.server['EV-PUB'] = publicEvent()
    const { call } = await import('frappe-ui')
    const p = panel({ event: { id: 'EV-PUB' }, mode: 'details' })
    await flush()
    expect(p.el.textContent).toContain('Going?')
    state.tabs.at(-1).emit('update:modelValue', 'Yes')
    await flush()
    expect(call).toHaveBeenCalledWith(
      'frappe.desk.doctype.event.event.update_attending_status',
      { event_name: 'EV-PUB', attendee: 'buyer@client.test', status: 'Yes' },
    )
  })
})

describe('CalendarEventPanel: Enter in the details view (FE-92)', () => {
  it('is left to a focused button', async () => {
    state.server['EV-K'] = doc('EV-K')
    const p = panel({ event: { id: 'EV-K' }, mode: 'details' })
    await flush()
    const button = p.el.querySelector('button')
    button.focus()
    const enter = new KeyboardEvent('keydown', {
      key: 'Enter',
      bubbles: true,
      cancelable: true,
    })
    button.dispatchEvent(enter)
    await flush()
    expect(enter.defaultPrevented).toBe(false)
    expect(p.emitted.edit).toHaveLength(0)
  })

  it('still opens Edit when nothing in particular has focus', async () => {
    state.server['EV-K'] = doc('EV-K')
    const p = panel({ event: { id: 'EV-K' }, mode: 'details' })
    await flush()
    const enter = new KeyboardEvent('keydown', {
      key: 'Enter',
      bubbles: true,
      cancelable: true,
    })
    document.body.dispatchEvent(enter)
    await flush()
    expect(enter.defaultPrevented).toBe(true)
    expect(p.emitted.edit).toHaveLength(1)
  })
})
