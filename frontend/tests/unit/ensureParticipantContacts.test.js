import { beforeEach, describe, expect, it, vi } from 'vitest'

// Typed attendees are resolved by the event's own save (crm.api.attendees),
// not from the browser. The browser's lookup saw only the Contacts the rep can
// read, so a meeting with another rep's customer gave that person a second
// Contact; and anything the browser is told about a hidden Contact tells the
// rep whose customer it is. So this asks the server nothing: it hands each
// typed address over as the address alone.

const call = vi.fn()
vi.mock('frappe-ui', async (original) => ({ ...(await original()), call }))
vi.mock('@/stores/users', () => ({ usersStore: () => ({}) }))

const { ensureParticipantContacts } = await import('@/composables/event')

const typed = (email, reference_docname = 'new') => ({
  email,
  reference_doctype: 'Contact',
  reference_docname,
})

describe('ensureParticipantContacts', () => {
  beforeEach(() => call.mockReset())

  it('asks the server nothing, and creates no Contact', async () => {
    await ensureParticipantContacts([
      typed('buyer@client.test'),
      typed('other@client.test', ''),
    ])

    expect(call).not.toHaveBeenCalled()
  })

  it('sends a typed address with no Contact named, for the save to resolve', async () => {
    const rows = await ensureParticipantContacts([
      typed('buyer@client.test'),
      typed(' pasted@client.test ', undefined),
      { email: 'bare@client.test' },
    ])

    expect(rows).toEqual([
      {
        email: 'buyer@client.test',
        reference_doctype: 'Contact',
        reference_docname: '',
      },
      {
        email: 'pasted@client.test',
        reference_doctype: 'Contact',
        reference_docname: '',
      },
      {
        email: 'bare@client.test',
        reference_doctype: 'Contact',
        reference_docname: '',
      },
    ])
  })

  it("never sends 'new', which frappe's link check refuses before any hook", async () => {
    const rows = await ensureParticipantContacts([typed('a@client.test')])

    expect(rows[0].reference_docname).not.toBe('new')
  })

  it('keeps a stored row as it is, its name and response included', async () => {
    const stored = {
      name: 'row-1',
      email: 'buyer@client.test',
      reference_doctype: 'Contact',
      reference_docname: '',
      attending: 'Yes',
    }

    const [row] = await ensureParticipantContacts([stored])

    expect(row).toEqual(stored)
    expect(row).not.toBe(stored)
  })

  it('leaves a row that already names its Contact or customer alone', async () => {
    const rows = await ensureParticipantContacts([
      typed('buyer@client.test', 'CONTACT-1'),
      {
        email: '',
        reference_doctype: 'CRM Organization',
        reference_docname: 'Impala',
      },
    ])

    expect(call).not.toHaveBeenCalled()
    expect(rows.map((r) => r.reference_docname)).toEqual([
      'CONTACT-1',
      'Impala',
    ])
  })

  it('leaves a row with no address for the server to refuse', async () => {
    const [row] = await ensureParticipantContacts([typed('', 'new')])

    expect(row.reference_docname).toBe('new')
  })

  it('passes an empty or missing list through', async () => {
    expect(await ensureParticipantContacts([])).toEqual([])
    expect(await ensureParticipantContacts(undefined)).toBeUndefined()
  })
})
