import { beforeEach, describe, expect, it, vi } from 'vitest'

// Giving a typed attendee a Contact before the event is saved. Audit
// fe_logic-4: the lookup read `Contact.email_id`, the primary address only, so
// somebody invited at their second address was given a second Contact. The
// server now looks across every address, among the Contacts this user can read.

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

  it('uses the Contact the server finds for the address', async () => {
    call.mockResolvedValueOnce('CONTACT-7')

    const rows = await ensureParticipantContacts([typed('second@client.test')])

    expect(call).toHaveBeenCalledTimes(1)
    expect(call).toHaveBeenCalledWith('crm.api.contact.find_by_email', {
      email: 'second@client.test',
    })
    expect(rows[0].reference_docname).toBe('CONTACT-7')
  })

  it('does not look in the primary-address column itself', async () => {
    call.mockResolvedValue('CONTACT-7')

    await ensureParticipantContacts([typed('second@client.test')])

    expect(call.mock.calls.map(([method]) => method)).not.toContain(
      'frappe.client.get_value',
    )
  })

  it('creates a Contact only when the server finds none', async () => {
    call.mockResolvedValueOnce(null).mockResolvedValueOnce({ name: 'NEW-1' })

    const rows = await ensureParticipantContacts([
      typed('fresh@client.test', ''),
    ])

    expect(call).toHaveBeenLastCalledWith('frappe.client.insert', {
      doc: {
        doctype: 'Contact',
        first_name: 'fresh',
        email_ids: [{ email_id: 'fresh@client.test', is_primary: 1 }],
      },
    })
    expect(rows[0].reference_docname).toBe('NEW-1')
  })

  it('leaves a row that already names its Contact alone', async () => {
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
})
