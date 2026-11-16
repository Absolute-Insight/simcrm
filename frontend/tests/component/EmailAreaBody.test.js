import { h, nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import EmailArea from '@/components/Activities/EmailArea.vue'
import { forgetEmailBodies } from '@/composables/useEmailBody'

// The timeline sends a snippet per email and the body only with the newest
// ones; any other body is fetched when the email is opened, once.
const { call } = vi.hoisted(() => ({ call: vi.fn() }))
vi.mock('frappe-ui', async (original) => ({ ...(await original()), call }))

vi.mock('@/components/Activities/EmailContent.vue', () => ({
  default: {
    props: ['content'],
    render() {
      return h('div', { 'data-email-content': '' }, this.content)
    },
  },
}))
vi.mock('@/components/Activities/TimelineTimestamp.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/AttachmentItem.vue', () => ({
  default: { render: () => null },
}))

const Button = {
  inheritAttrs: false,
  render() {
    const { tooltip, label, onClick, ...rest } = this.$attrs
    const data = Object.fromEntries(
      Object.entries(rest).filter(([k]) => k.startsWith('data-')),
    )
    return h('button', { ...data, 'data-tooltip': tooltip, onClick }, label)
  },
}

function composer() {
  const inserted = []
  const chain = new Proxy(
    {},
    {
      get: (_, k) => {
        if (k === 'run') return () => {}
        if (k === 'insertContent')
          return (content) => (inserted.push(content), chain)
        return () => chain
      },
    },
  )
  const doc = { forEach: () => {} }
  return {
    show: false,
    inserted,
    editor: { editor: { chain: () => chain, state: { doc } } },
  }
}

function email(name, data = {}) {
  return {
    name,
    activity_type: 'communication',
    communication_type: 'Communication',
    communication_date: '2026-10-29 09:00:00',
    data: {
      subject: 'Quote Q-1042',
      snippet: 'Please find the quote attached & priced',
      sender: 'buyer@customer.co.za',
      sender_full_name: 'Buyer',
      recipients: 'thabo@mbp-engineering.co.za',
      sent_or_received: 'Received',
      cc: null,
      bcc: null,
      attachments: [],
      ...data,
    },
  }
}

function render(activity, emailBox = composer()) {
  return {
    ...mount(EmailArea, { props: { activity, emailBox }, stubs: { Button } }),
    emailBox,
  }
}

const flush = async () => {
  for (let i = 0; i < 5; i++) await nextTick()
  await new Promise((r) => setTimeout(r))
}

const toggle = (el) => el.querySelector('[data-email-toggle]')

beforeEach(() => {
  forgetEmailBodies()
  call.mockReset()
})

describe('EmailArea closed', () => {
  it('shows the snippet and fetches nothing', () => {
    const { el } = render(email('c-1'))
    expect(toggle(el).getAttribute('aria-expanded')).toBe('false')
    expect(el.querySelector('[data-email-snippet]').textContent).toContain(
      'Please find the quote attached & priced',
    )
    expect(el.querySelector('[data-email-content]')).toBeNull()
    expect(call).not.toHaveBeenCalled()
  })

  // Rows above the newest must not grow while the timeline scrolls to it:
  // closed, every line is clipped to one, whatever the recipients or body.
  it('is one line per field, so its height is fixed', () => {
    const { el } = render(
      email('c-1', { recipients: Array(30).fill('a@b.co').join(', ') }),
    )
    const lines = toggle(el).querySelectorAll(':scope > div > div')
    expect(lines.length).toBe(3)
    expect(lines[0].className).toContain('truncate')
    expect(lines[1].className).toContain('truncate')
    expect(lines[2].querySelector('.truncate')).not.toBeNull()
  })
})

describe('EmailArea opened by default', () => {
  it('paints the body it came with on the first render, without a request', () => {
    const { el } = render(email('c-2', { content: '<p>Full body</p>' }))
    expect(toggle(el).getAttribute('aria-expanded')).toBe('true')
    expect(el.querySelector('[data-email-content]').textContent).toBe(
      '<p>Full body</p>',
    )
    expect(el.querySelector('[data-email-snippet]')).toBeNull()
    expect(call).not.toHaveBeenCalled()
  })
})

describe('EmailArea fetch on expand', () => {
  it('fetches the body once and keeps it', async () => {
    call.mockResolvedValue({ name: 'c-3', content: '<p>Fetched</p>' })
    const { el } = render(email('c-3'))

    toggle(el).click()
    await nextTick()
    expect(el.querySelector('[data-email-loading]')).not.toBeNull()
    await flush()
    expect(call).toHaveBeenCalledTimes(1)
    expect(call).toHaveBeenCalledWith('crm.api.activities.get_email_body', {
      name: 'c-3',
    })
    expect(el.querySelector('[data-email-content]').textContent).toBe(
      '<p>Fetched</p>',
    )

    // closed and opened again, and on a card for the same email (a reload)
    toggle(el).click()
    await nextTick()
    toggle(el).click()
    await flush()
    const again = render(email('c-3')).el
    toggle(again).click()
    await flush()
    expect(again.querySelector('[data-email-content]').textContent).toBe(
      '<p>Fetched</p>',
    )
    expect(call).toHaveBeenCalledTimes(1)
  })

  it('asks once when opened twice before the answer arrives', async () => {
    let answer
    call.mockReturnValue(new Promise((r) => (answer = r)))
    const a = render(email('c-4')).el
    const b = render(email('c-4')).el
    toggle(a).click()
    toggle(b).click()
    answer({ content: '<p>Once</p>' })
    await flush()
    expect(call).toHaveBeenCalledTimes(1)
    expect(b.querySelector('[data-email-content]').textContent).toBe(
      '<p>Once</p>',
    )
  })

  it('says it failed and fetches again on Retry', async () => {
    call.mockRejectedValueOnce(new Error('Email not found'))
    const { el } = render(email('c-5'))

    toggle(el).click()
    await flush()
    const error = el.querySelector('[data-email-error]')
    expect(error.getAttribute('role')).toBe('alert')
    expect(error.className).toContain('text-ink-red-9')
    expect(el.querySelector('[data-email-content]')).toBeNull()

    call.mockResolvedValueOnce({ content: '<p>Second time</p>' })
    el.querySelector('[data-email-retry]').click()
    await flush()
    expect(call).toHaveBeenCalledTimes(2)
    expect(el.querySelector('[data-email-error]')).toBeNull()
    expect(el.querySelector('[data-email-content]').textContent).toBe(
      '<p>Second time</p>',
    )
  })
})

describe('EmailArea reply on a closed email', () => {
  it('fetches the body first and quotes it', async () => {
    call.mockResolvedValue({ content: '<p>Original words</p>' })
    const { el, emailBox } = render(email('c-6'))

    el.querySelector('[data-tooltip="Reply"]').click()
    await flush()

    expect(call).toHaveBeenCalledTimes(1)
    expect(emailBox.show).toBe(true)
    expect(emailBox.editor.toEmails).toEqual(['buyer@customer.co.za'])
    expect(emailBox.inserted).toEqual([
      '<blockquote><p>Original words</p></blockquote>',
    ])
  })

  it('quotes an inline body in the same tick, without a request', () => {
    const { el, emailBox } = render(
      email('c-7', { content: '<p>Already here</p>' }),
    )
    el.querySelector('[data-tooltip="Reply All"]').click()
    expect(call).not.toHaveBeenCalled()
    expect(emailBox.inserted).toEqual([
      '<blockquote><p>Already here</p></blockquote>',
    ])
  })

  it('does not open the composer when the body cannot be loaded', async () => {
    call.mockRejectedValue(new Error('Email not found'))
    const { el, emailBox } = render(email('c-8'))
    el.querySelector('[data-tooltip="Reply"]').click()
    await flush()
    expect(emailBox.show).toBe(false)
    expect(emailBox.inserted).toEqual([])
  })
})

describe('EmailArea the reader may not open', () => {
  // What crm.api.activities.hide_email_content sends: the colleague on it,
  // the direction and the date -- no subject, no address.
  const hidden = (data = {}) => ({
    name: 'c-9',
    activity_type: 'communication',
    communication_type: 'Communication',
    communication_date: '2026-11-03 09:00:00',
    data: {
      hidden: true,
      internal_party: 'Emily Chen',
      internal_party_user: 'emily@mbp-engineering.co.za',
      sent_or_received: 'Sent',
      delivery_status: 'Sent',
      attachments: [],
      ...data,
    },
  })
  const summary = (el) =>
    el.querySelector('[data-email-hidden-summary]').textContent.trim()

  it('names the colleague who emailed the contact, and nothing else', () => {
    const { el } = render(hidden())
    expect(summary(el)).toBe('Emily Chen emailed this contact')
    const row = el.querySelector('[data-email-hidden]')
    expect(row.className).toContain('text-ink-gray-6')
    expect(row.textContent).toContain('Restricted email:')
    // the lock is decoration; the words carry the meaning
    expect(row.firstElementChild.getAttribute('aria-hidden')).toBe('true')
    expect(row.textContent).not.toContain('undefined')
    // no status badge, no To line, no snippet or files
    expect(row.textContent).not.toContain('Sent')
    expect(row.textContent).not.toContain('To')
    expect(el.querySelector('[data-email-snippet]')).toBeNull()
  })

  it('says the colleague received it for inbound mail', () => {
    const { el } = render(hidden({ sent_or_received: 'Received' }))
    expect(summary(el)).toBe('Emily Chen received an email from this contact')
  })

  it('says a colleague when no one on our side is named', () => {
    const { el } = render(
      hidden({ internal_party: undefined, internal_party_user: null }),
    )
    expect(summary(el)).toBe('A colleague emailed this contact')
  })

  it('offers nothing to open, retry, reply to or reschedule', () => {
    const { el } = render(
      hidden({
        delivery_status: 'Scheduled',
        send_after: '2026-11-20 09:00:00',
        scheduled_by_me: true,
      }),
    )
    expect(el.querySelector('[data-email-toggle]')).toBeNull()
    expect(el.querySelector('[data-email-retry]')).toBeNull()
    expect(el.querySelector('[data-tooltip="Reply"]')).toBeNull()
    expect(el.querySelector('[data-tooltip="Reply All"]')).toBeNull()
    expect(
      el.querySelector('[data-tooltip="Scheduled email actions"]'),
    ).toBeNull()
    expect(el.querySelector('button')).toBeNull()
    expect(call).not.toHaveBeenCalled()
  })
})

describe('EmailArea reply on two closed emails in turn', () => {
  it('fills the composer with the latest click, not the slower fetch', async () => {
    const answers = {}
    call.mockImplementation(
      (_, { name }) => new Promise((r) => (answers[name] = r)),
    )
    const emailBox = composer()
    const a = render(email('c-10', { subject: 'First' }), emailBox).el
    const b = render(email('c-11', { subject: 'Second' }), emailBox).el

    a.querySelector('[data-tooltip="Reply"]').click()
    b.querySelector('[data-tooltip="Reply"]').click()
    answers['c-11']({ content: '<p>second body</p>' })
    await flush()
    answers['c-10']({ content: '<p>first body</p>' })
    await flush()

    expect(emailBox.inserted).toEqual([
      '<blockquote><p>second body</p></blockquote>',
    ])
    expect(emailBox.editor.subject).toBe('Re: Second')
  })
})
