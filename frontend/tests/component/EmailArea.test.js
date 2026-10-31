import { h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import EmailArea from '@/components/Activities/EmailArea.vue'

// Children that render the body, files and time pull in the app's stores;
// none of them take part in addressing a reply.
const { blank } = vi.hoisted(() => ({
  blank: () => ({ default: { render: () => null } }),
}))
vi.mock('@/components/Activities/EmailContent.vue', blank)
vi.mock('@/components/Activities/TimelineTimestamp.vue', blank)
vi.mock('@/components/AttachmentItem.vue', blank)

// The app registers Button globally; a plain button carrying the tooltip is
// enough to find and click Reply / Reply All.
const Button = {
  inheritAttrs: false,
  render() {
    return h('button', {
      'data-tooltip': this.$attrs.tooltip,
      onClick: this.$attrs.onClick,
    })
  },
}

function composer() {
  const chain = new Proxy(
    {},
    { get: (_, k) => (k === 'run' ? () => {} : () => chain) },
  )
  return { show: false, editor: { editor: { chain: () => chain } } }
}

function email(data) {
  return {
    activity_type: 'communication',
    communication_type: 'Communication',
    communication_date: '2026-10-29 09:00:00',
    data: {
      subject: 'Quote Q-1042',
      content: '<p>Please find the quote attached.</p>',
      sender_full_name: 'Thabo Rep',
      cc: null,
      bcc: null,
      attachments: [],
      ...data,
    },
  }
}

function clickReply(activity, tooltip) {
  const emailBox = composer()
  const w = mount(EmailArea, {
    props: { activity, emailBox },
    stubs: { Button },
  })
  w.el.querySelector(`[data-tooltip="${tooltip}"]`).click()
  w.unmount()
  return emailBox.editor
}

describe('EmailArea reply addressing', () => {
  const sent = email({
    sent_or_received: 'Sent',
    sender: 'thabo@mbp-engineering.co.za',
    recipients: 'buyer@customer.co.za, ops@customer.co.za',
    cc: 'finance@customer.co.za',
  })

  it('replies to the original recipients of an email the rep sent', () => {
    const editor = clickReply(sent, 'Reply')
    expect(editor.toEmails).toEqual([
      'buyer@customer.co.za',
      'ops@customer.co.za',
    ])
    expect(editor.ccEmails).toEqual([])
  })

  it('keeps the CC line and leaves the rep out on Reply All to sent mail', () => {
    const editor = clickReply(sent, 'Reply All')
    expect(editor.toEmails).toEqual([
      'buyer@customer.co.za',
      'ops@customer.co.za',
    ])
    expect(editor.ccEmails).toEqual(['finance@customer.co.za'])
    expect(editor.ccEmails).not.toContain('thabo@mbp-engineering.co.za')
  })

  it('still replies to the sender of a received email', () => {
    const received = email({
      sent_or_received: 'Received',
      sender: 'buyer@customer.co.za',
      recipients: 'thabo@mbp-engineering.co.za',
    })
    const editor = clickReply(received, 'Reply')
    expect(editor.toEmails).toEqual(['buyer@customer.co.za'])
    expect(editor.replyAddresses).toContain('thabo@mbp-engineering.co.za')
  })
})
