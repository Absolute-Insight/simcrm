import { describe, it, expect } from 'vitest'
import { customTransportChanges } from '@/utils/emailAccountTransport'

// As create_email_account stores a Custom account on 587 with IMAP over SSL.
const created = {
  smtp_port: '587',
  use_tls: 1,
  use_ssl_for_outgoing: 0,
  use_ssl: 1,
  use_starttls: 0,
}

describe('customTransportChanges', () => {
  it('switches outgoing to SSL when the port becomes 465, and back', () => {
    expect(
      customTransportChanges({ ...created, smtp_port: '465' }, created),
    ).toEqual({ use_ssl_for_outgoing: 1, use_tls: 0 })
    const on465 = { ...created, smtp_port: '465', use_tls: 0 }
    expect(
      customTransportChanges({ ...on465, smtp_port: '587' }, on465),
    ).toEqual({ use_ssl_for_outgoing: 0, use_tls: 1 })
  })

  it('switches incoming to STARTTLS on 143 when SSL is unticked, and back', () => {
    expect(
      customTransportChanges({ ...created, use_ssl: false }, created),
    ).toEqual({ use_ssl: 0, use_starttls: 1, incoming_port: '143' })
    const plain = { ...created, use_ssl: 0, use_starttls: 1 }
    expect(customTransportChanges({ ...plain, use_ssl: true }, plain)).toEqual({
      use_ssl: 1,
      use_starttls: 0,
      incoming_port: '993',
    })
  })

  it('leaves the flags alone when neither the port nor SSL changed', () => {
    // a desk-configured account on port 25 without TLS keeps its setup
    const desk = { smtp_port: '25', use_tls: 0, use_ssl: 1 }
    expect(customTransportChanges({ ...desk, use_ssl: true }, desk)).toEqual({})
    expect(
      customTransportChanges({ ...created, smtp_port: ' 587 ' }, created),
    ).toEqual({})
  })
})
