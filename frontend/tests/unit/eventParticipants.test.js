import { describe, expect, it } from 'vitest'
import { normalizeParticipants } from '@/composables/event'

// The participant rows an event is saved with. Audit FE-02: rows without an
// email were dropped and the rest lost `name` and `attending`, so editing a
// visit's attendees deleted its CRM Organization row and reset every RSVP.

describe('normalizeParticipants', () => {
  it('keeps e-mail-less rows, row names and RSVPs', () => {
    expect(
      normalizeParticipants([
        {
          name: 'p-org',
          email: null,
          reference_doctype: 'CRM Organization',
          reference_docname: 'Impala Springs',
          parent: 'EV-1',
          idx: 1,
        },
        {
          name: 'p-buyer',
          email: 'buyer@client.test',
          reference_doctype: 'Contact',
          reference_docname: 'C-1',
          attending: 'Maybe',
        },
      ]),
    ).toEqual([
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
        reference_docname: 'C-1',
        attending: 'Maybe',
      },
    ])
  })

  it('drops a repeated reference, or a repeated address not yet a Contact', () => {
    const org = {
      email: '',
      reference_doctype: 'CRM Organization',
      reference_docname: 'Impala Springs',
    }
    expect(
      normalizeParticipants([
        org,
        { ...org },
        { email: 'a@client.test', reference_docname: 'new' },
        { email: 'a@client.test', reference_docname: 'new' },
        { email: 'b@client.test' },
        {},
      ]),
    ).toEqual([
      org,
      {
        email: 'a@client.test',
        reference_doctype: 'Contact',
        reference_docname: 'new',
      },
      {
        email: 'b@client.test',
        reference_doctype: 'Contact',
        reference_docname: '',
      },
    ])
  })
})
