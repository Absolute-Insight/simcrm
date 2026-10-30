import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, toRaw } from 'vue'
import { mount } from './mount.js'
import {
  Button,
  FormControl,
  formControls,
  setConfig,
} from './telephony/frappeUi.js'
import { editors } from './telephony/experimental.js'
import ExotelCallUI from '@/components/Telephony/ExotelCallUI.vue'

const socket = vi.hoisted(() => ({ listeners: {} }))

vi.mock('frappe-ui', () => import('./telephony/frappeUi.js'))
vi.mock('frappe-ui/experimental', () => import('./telephony/experimental.js'))
// socket.io: on() adds a listener, off(event, fn) removes that one, off(event)
// removes every listener for the event
vi.mock('@/stores/global', () => ({
  globalStore: () => ({
    $socket: {
      on: (event, fn) => (socket.listeners[event] ||= []).push(fn),
      off: (event, fn) => {
        socket.listeners[event] = fn
          ? (socket.listeners[event] || []).filter((f) => f !== fn)
          : []
      },
    },
  }),
}))
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: 'rep@example.com' }),
}))
vi.mock('@/stores/users', async () => {
  const { reactive } = await import('vue')
  return {
    usersStore: () => ({
      users: reactive({ data: { crmUsers: [] } }),
      getUser: () => ({ full_name: '' }),
    }),
  }
})
vi.mock('@/utils', () => ({
  taskStatusOptions: () => [],
  taskPriorityOptions: () => [],
  getFormat: () => '',
}))
vi.mock('@/components/Controls/Link.vue', () => ({
  default: { name: 'Link', render: () => null },
}))
vi.mock('@/components/UserAvatar.vue', () => ({
  default: { name: 'UserAvatar', render: () => null },
}))

const flush = async (rounds = 6) => {
  for (let i = 0; i < rounds; i++) {
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

const button = (el, by, value) =>
  [...el.querySelectorAll('button.stub-Button')].find(
    (b) => b.dataset[by] === value,
  )
const saveOrUpdate = (el) =>
  button(el, 'label', 'Save') || button(el, 'label', 'Update')

const deliver = (data) =>
  (socket.listeners.exotel_call || []).forEach((fn) => fn(data))
const callEnded = (sid) => ({
  CallSid: sid,
  EventType: 'terminal',
  Direction: 'outbound-api',
  Status: 'completed',
  DialCallDuration: '42',
})
const ringingIn = (sid, from) => ({
  CallSid: sid,
  EventType: 'Dial',
  Direction: 'incoming',
  Status: 'busy',
  CallFrom: from,
  From: from,
  AgentEmail: 'rep@example.com',
})

let requests, sids, noteNames, taskNames

beforeEach(() => {
  socket.listeners = {}
  requests = []
  sids = noteNames = taskNames = 0
  setConfig('resourceFetcher', async ({ url, params }) => {
    requests.push({ url, params: JSON.parse(JSON.stringify(params || {})) })
    if (url.endsWith('make_a_call')) return { CallSid: `SID${++sids}` }
    if (url.endsWith('add_note_to_call_log'))
      return { name: params.note.name || `NOTE-${++noteNames}` }
    if (url.endsWith('add_task_to_call_log'))
      return { name: params.task.name || `TASK-${++taskNames}` }
    return { full_name: 'Customer', mobile_no: params?.phone_number }
  })
})

// TaskPanel uses Button and FormControl as the app registers them, globally
const mountCallUI = () =>
  mount(ExotelCallUI, { stubs: { Button, FormControl } })

async function dial(w, number) {
  w.vm.makeOutgoingCall(number)
  await flush()
}

const lastRequest = (method) =>
  requests.filter((r) => r.url.endsWith(method)).at(-1)

describe('ExotelCallUI: a note or task belongs to its own call', () => {
  it('a note written on the next call is a new note, not an edit of the last one', async () => {
    const w = mountCallUI()
    w.vm.setup()
    await dial(w, '+27115550001')
    button(w.el, 'tooltip', 'Add a Note').click()
    await flush()
    editors.at(-1).type('<p>Call 1: wants a quote for 40 valves</p>')
    await flush()
    button(w.el, 'label', 'Save').click()
    await flush()
    deliver(callEnded('SID1'))
    await flush()

    // the rep goes to the next lead and calls, the popup still open
    await dial(w, '+27115550002')
    button(w.el, 'tooltip', 'Add a Note').click()
    await flush()
    expect(editors.at(-1).props.content).toBe('')
    editors.at(-1).type('<p>Call 2: not interested</p>')
    await flush()
    saveOrUpdate(w.el).click()
    await flush()

    const saved = lastRequest('add_note_to_call_log').params
    expect(saved.call_sid).toBe('SID2')
    expect(saved.note.name).toBe('')
  })

  it('after the popup is closed, the next call starts with an empty task that saves', async () => {
    const w = mountCallUI()
    w.vm.setup()
    await dial(w, '+27115550001')
    button(w.el, 'tooltip', 'Add a Task').click()
    await flush()
    formControls.at(-1).type('Send quote')
    await flush()
    button(w.el, 'label', 'Save').click()
    await flush()
    deliver(callEnded('SID1'))
    await flush()
    // the X, which only shows once a call has ended
    const close = [...w.el.querySelectorAll('button.stub-Button')].find(
      (b) => !b.dataset.label && !b.dataset.tooltip,
    )
    close.click()
    await flush()

    await dial(w, '+27115550002')
    button(w.el, 'tooltip', 'Add a Task').click()
    await flush()
    expect(formControls.at(-1).props.modelValue).toBe('')
    formControls.at(-1).type('Book site visit')
    await flush()
    saveOrUpdate(w.el).click()
    await flush()

    const saved = lastRequest('add_task_to_call_log').params
    expect(saved.call_sid).toBe('SID2')
    expect(saved.task).toMatchObject({ name: '', title: 'Book site visit' })
  })

  it('a call that rings in while the last one is still open starts with its own note and task', async () => {
    const w = mountCallUI()
    w.vm.setup()
    await dial(w, '+27115550001')
    button(w.el, 'tooltip', 'Add a Task').click()
    await flush()
    formControls.at(-1).type('Send quote')
    await flush()
    button(w.el, 'label', 'Save').click()
    await flush()
    button(w.el, 'tooltip', 'Add a Note').click()
    await flush()
    editors.at(-1).type('<p>Call 1: wants a quote for 40 valves</p>')
    await flush()
    saveOrUpdate(w.el).click()
    await flush()
    deliver(callEnded('SID1'))
    await flush()

    // a customer calls in, the popup still open on "Call ended"
    deliver(ringingIn('SID2', '+27115550003'))
    await flush()
    expect(w.el.textContent).toContain('Incoming call')
    button(w.el, 'tooltip', 'Add a Note').click()
    await flush()
    expect(editors.at(-1).props.content).toBe('')
    editors.at(-1).type('<p>Call 2: not interested</p>')
    await flush()
    saveOrUpdate(w.el).click()
    await flush()

    const saved = lastRequest('add_note_to_call_log').params
    expect(saved.call_sid).toBe('SID2')
    expect(saved.note.name).toBe('')
    // and call 1's task is not rewritten and moved onto call 2
    expect(lastRequest('add_task_to_call_log').params.call_sid).toBe('SID1')
  })

  it('a call that rings in while the last one is minimised opens the popup', async () => {
    const w = mountCallUI()
    w.vm.setup()
    await dial(w, '+27115550001')
    deliver(callEnded('SID1'))
    await flush()
    button(w.el, 'tooltip', 'Minimize').click()
    await flush()

    deliver(ringingIn('SID2', '+27115550003'))
    await flush()

    const [small, popup] = w.el.firstElementChild.children
    expect(popup.style.display).toBe('')
    expect(small.style.display).toBe('none')
    expect(popup.textContent).toContain('Incoming call')
  })
})

describe('ExotelCallUI: one socket listener', () => {
  it('a second setup() adds no second listener and no second call timer', async () => {
    const started = []
    const cleared = new Set()
    const realSet = globalThis.setInterval
    const realClear = globalThis.clearInterval
    globalThis.setInterval = (fn, ms) => {
      const id = realSet(fn, ms)
      started.push(id)
      return id
    }
    // CountUpTimer keeps the id in a ref(), so it comes back wrapped
    globalThis.clearInterval = (id) => {
      cleared.add(toRaw(id))
      return realClear(id)
    }
    try {
      const w = mountCallUI()
      w.vm.setup()
      // CallUI calls setup() again whenever telephony is switched back on
      w.vm.setup()
      await dial(w, '+27115550001')
      deliver({
        CallSid: 'SID1',
        EventType: 'answered',
        Direction: 'outbound-api',
        Status: 'in-progress',
        'Legs[0][Status]': 'in-progress',
        'Legs[1][Status]': 'in-progress',
      })
      deliver(callEnded('SID1'))
      await flush()

      expect(socket.listeners.exotel_call).toHaveLength(1)
      expect(started.filter((id) => !cleared.has(id))).toHaveLength(0)
    } finally {
      started.forEach((id) => realClear(id))
      globalThis.setInterval = realSet
      globalThis.clearInterval = realClear
    }
  })

  it('unmounting removes its own listener and leaves the others', async () => {
    const other = () => {}
    socket.listeners.exotel_call = [other]
    const w = mountCallUI()
    w.vm.setup()

    w.unmount()

    expect(socket.listeners.exotel_call).toEqual([other])
  })
})
