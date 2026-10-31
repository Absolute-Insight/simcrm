import { describe, expect, it, vi } from 'vitest'
import { setConfig } from 'frappe-ui'

// useEvent against frappe-ui's real list resources; only the server is fake.
// Audit FE-01 (child tables never fetched, so an edit from a record's Events
// tab saved them back empty) and FE-12 (`limit` is not a list resource
// option: every list stopped at 20, newest-created first).

vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    getUser: (email) => ({ full_name: `Full ${email}`, user_image: '' }),
  }),
}))
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: 'rep@mbp.test' }),
}))
vi.mock('@/data/userSettings', () => ({
  getUserSettings: async () => null,
  useUserSettings: () => ({ save: async () => {} }),
}))

const { useEvent } = await import('@/composables/event')

const requests = []
const server = { events: [], participants: [], notifications: [] }

setConfig('resourceFetcher', async ({ params = {} }) => {
  requests.push(params)
  const rows = {
    Event: server.events,
    'Event Participants': server.participants,
    'Event Notifications': server.notifications,
  }[params.doctype]
  return (rows || []).slice(0, params.limit_page_length)
})

const settle = () => new Promise((r) => setTimeout(r, 20))

function visit(name, extra = {}) {
  return {
    name,
    subject: `Visit ${name}`,
    owner: 'rep@mbp.test',
    starts_on: '2026-10-30 09:00:00',
    ends_on: '2026-10-30 10:00:00',
    ...extra,
  }
}

describe('useEvent: the Events tab of a deal', () => {
  it('loads each event with its participants and reminders', async () => {
    requests.length = 0
    server.events = [visit('EV-1'), visit('EV-2')]
    server.participants = [
      // a planner visit's customer: CRM Organization, no email
      {
        name: 'p-org',
        parent: 'EV-1',
        email: null,
        reference_doctype: 'CRM Organization',
        reference_docname: 'Impala Springs',
      },
      {
        name: 'p-buyer',
        parent: 'EV-1',
        email: 'buyer@client.test',
        reference_doctype: 'Contact',
        reference_docname: 'C-1',
        attending: 'Yes',
      },
    ]
    server.notifications = [
      {
        name: 'n1',
        parent: 'EV-1',
        type: 'Email',
        before: 10,
        interval: 'minutes',
      },
    ]

    const { events } = useEvent({
      doctype: 'CRM Deal',
      docname: 'CRM-DEAL-FE01',
    })
    await settle()

    const asked = requests.map((r) => r.doctype)
    expect(asked).toContain('Event Participants')
    expect(asked).toContain('Event Notifications')
    const childRequest = requests.find(
      (r) => r.doctype === 'Event Participants',
    )
    expect(childRequest.filters.parent).toEqual(['in', ['EV-1', 'EV-2']])

    const [first, second] = events.value
    expect(first.event_participants.map((p) => p.name)).toEqual([
      'p-org',
      'p-buyer',
    ])
    expect(first.notifications).toHaveLength(1)
    // loaded, and none: an empty table, not a missing one
    expect(second.event_participants).toEqual([])
    expect(second.notifications).toEqual([])
    expect(first.owner).toMatchObject({
      label: 'Full rep@mbp.test',
      name: 'rep@mbp.test',
    })
    // the org row is named by its reference, not shown as the viewer
    expect(first.participants.map((p) => p.label)).toEqual([
      'Full rep@mbp.test',
      'Impala Springs',
      'Full buyer@client.test',
    ])
  })

  it('reloads the child rows when the event list reloads', async () => {
    server.events = [visit('EV-3')]
    server.participants = []
    server.notifications = []
    const { events, eventsResource } = useEvent({
      doctype: 'CRM Deal',
      docname: 'CRM-DEAL-RELOAD',
    })
    await settle()
    expect(events.value[0].event_participants).toEqual([])

    // an attendee added and saved elsewhere
    server.participants = [
      { name: 'p1', parent: 'EV-3', email: 'new@client.test' },
    ]
    await eventsResource.reload()
    await settle()
    expect(events.value[0].event_participants.map((p) => p.email)).toEqual([
      'new@client.test',
    ])
  })

  it('leaves a child table unloaded when its page came back full', async () => {
    server.events = [visit('EV-4')]
    server.participants = Array.from({ length: 500 }, (_, i) => ({
      name: `p${i}`,
      parent: 'EV-4',
      email: `guest${i}@client.test`,
    }))
    server.notifications = []
    const { events } = useEvent({
      doctype: 'CRM Deal',
      docname: 'CRM-DEAL-TRUNCATED',
    })
    await settle()
    // a possibly short list is not offered as the event's own: saved back,
    // it would delete the rows it is missing
    expect(events.value[0].event_participants).toBeUndefined()
    expect(events.value[0].notifications).toEqual([])
  })

  it('asks for 50 events, not the default 20', async () => {
    requests.length = 0
    server.events = Array.from({ length: 30 }, (_, i) => visit(`EV-L${i}`))
    const { events } = useEvent({
      doctype: 'CRM Deal',
      docname: 'CRM-DEAL-FE12',
      participants: false,
      notifications: false,
    })
    await settle()
    const request = requests.find((r) => r.doctype === 'Event')
    expect(request.limit_page_length).toBe(50)
    expect(events.value).toHaveLength(30)
  })
})

describe('useEventNotifications: the bell Events tab', () => {
  it('lists the soonest events first', async () => {
    const { useEventNotifications } = await import('@/data/notifications')
    const { eventsResource } = useEventNotifications()
    expect(eventsResource.pageLength).toBe(50)
    expect(eventsResource.orderBy).toBe('starts_on asc')
  })
})
