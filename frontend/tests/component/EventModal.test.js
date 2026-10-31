import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import { flush, modalStubs, translation } from './stubs.js'
import EventModal from '@/components/Modals/EventModal.vue'

// The real EventModal and composables/event (time rules, validation); the
// Event list resource records what is saved.
const S = vi.hoisted(() => ({ insert: [], setValue: [] }))

vi.mock('frappe-ui', async (importOriginal) => {
  const none = (name) => ({ name, render: () => null })
  const events = () => ({
    data: [],
    reload: () => Promise.resolve(),
    update() {},
    insert: { submit: (doc) => S.insert.push(doc) },
    setValue: { submit: (doc) => S.setValue.push(doc) },
    delete: { submit() {} },
  })
  return {
    ...(await importOriginal()),
    createListResource: events,
    createResource: events,
    Switch: none('Switch'),
    DatePicker: none('DatePicker'),
    TimePicker: none('TimePicker'),
    Dropdown: none('Dropdown'),
  }
})
vi.mock('frappe-ui/experimental', () => ({
  TextEditor: { name: 'TextEditor', render: () => null },
  CalendarColorMap: {},
}))
vi.mock('@/stores/global', () => ({ globalStore: () => ({ $dialog() {} }) }))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: () => ({}) }),
}))
vi.mock('@/components/Calendar/EventNotifications.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/Calendar/Attendee.vue', () => ({
  default: { render: () => null },
}))

async function open(event) {
  const w = mount(EventModal, {
    props: {
      modelValue: true,
      doctype: 'CRM Deal',
      docname: 'DEAL-1',
      ...(event ? { event } : {}),
    },
    stubs: {
      ...modalStubs,
      ...Object.fromEntries(
        [
          'TextInput',
          'FormControl',
          'LucideTrash2',
          'LucideCopy',
          'LucideX',
        ].map((name) => [name, { render: () => null }]),
      ),
    },
    plugins: [translation],
  })
  await flush()
  return w.vm.$.setupState
}

beforeEach(() => {
  S.insert.length = 0
  S.setValue.length = 0
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 30, 23, 10)) // 30 Oct, 23:10 local
})
afterEach(() => vi.useRealTimers())

describe('EventModal dates', () => {
  it('a new event begun after 23:00 and moved to 09:00 ends that day', async () => {
    // The form shows "Oct 30, 2026  23:10  00:10"; the rep sets the start.
    const m = await open()
    m.updateTime('09:00', true) // the end follows to 10:00
    m._event.title = 'Site visit'
    m.update()
    await flush() // the insert waits on the attendees' Contacts
    expect(m.error).toBe(null)
    expect(S.insert).toHaveLength(1)
    expect(S.insert[0]).toMatchObject({
      starts_on: '2026-10-30 09:00',
      ends_on: '2026-10-30 10:00',
    })
  })

  it('a new event begun after 23:00 can be created as seeded', async () => {
    const m = await open()
    m._event.title = 'Late call'
    m.update()
    await flush()
    expect(m.error).toBe(null)
    expect(S.insert[0]).toMatchObject({
      starts_on: '2026-10-30 23:10',
      ends_on: '2026-10-31 00:10',
    })
  })

  it('an existing overnight event can be saved again', async () => {
    const m = await open({
      name: 'EV-1',
      subject: 'Night shift',
      starts_on: '2026-10-28 22:00:00',
      ends_on: '2026-10-29 01:00:00',
      all_day: 0,
    })
    m._event.title = 'Night shift (moved)'
    m.update()
    expect(m.error).toBe(null)
    expect(S.setValue[0]).toMatchObject({
      starts_on: '2026-10-28 22:00',
      ends_on: '2026-10-29 01:00',
    })
  })

  it('an overnight event moved to another day still ends the morning after', async () => {
    const m = await open({
      name: 'EV-2',
      subject: 'Night shift',
      starts_on: '2026-10-28 22:00:00',
      ends_on: '2026-10-29 01:00:00',
      all_day: 0,
    })
    m.updateDate('2026-11-02')
    m.update()
    expect(S.setValue[0]).toMatchObject({
      starts_on: '2026-11-02 22:00',
      ends_on: '2026-11-03 01:00',
    })
  })

  it('still refuses an end time equal to the start', async () => {
    const m = await open({
      name: 'EV-3',
      subject: 'Call',
      starts_on: '2026-10-28 09:00:00',
      ends_on: '2026-10-28 10:00:00',
      all_day: 0,
    })
    m.updateTime('09:00')
    expect(m.error).toBe('End Time Should Be After Start Time')
    expect(m._event.toTime).toBe('10:00')
    expect(m._event.toDate).toBe('2026-10-28')
  })
})
