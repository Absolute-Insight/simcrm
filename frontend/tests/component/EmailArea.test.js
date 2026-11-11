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

// `draft` is what the rep has already typed, as the editor's top-level nodes.
function composer(draft = []) {
  const inserted = []
  const chain = new Proxy(
    {},
    {
      get: (_, k) => {
        if (k === 'run') return () => {}
        if (k === 'insertContentAt')
          return (at, content) => (inserted.push({ at, content }), chain)
        return () => chain
      },
    },
  )
  const nodes = draft.map((node) => ({
    type: { name: node.type },
    toJSON: () => node,
  }))
  const doc = { forEach: (fn) => nodes.forEach(fn) }
  return {
    show: false,
    inserted,
    editor: { editor: { chain: () => chain, state: { doc } } },
  }
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

function clickReply(activity, tooltip, emailBox = composer()) {
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

  // Upstream frappe/crm #3309: Reply used to clear the composer first, so a
  // rep who had started typing and then picked the email to answer lost it.
  describe('what was already typed', () => {
    const received = email({
      sent_or_received: 'Received',
      sender: 'buyer@customer.co.za',
      recipients: 'thabo@mbp-engineering.co.za',
    })
    const typed = { type: 'paragraph', content: [{ type: 'text', text: 'Hi' }] }

    it('is kept above the quoted email', () => {
      const emailBox = composer([typed])
      clickReply(received, 'Reply', emailBox)
      expect(emailBox.inserted).toEqual([{ at: 0, content: [typed] }])
    })

    it('drops an earlier quote and whatever sits under it', () => {
      const emailBox = composer([
        typed,
        { type: 'blockquote' },
        { type: 'paragraph' },
      ])
      clickReply(received, 'Reply All', emailBox)
      expect(emailBox.inserted).toEqual([{ at: 0, content: [typed] }])
    })

    it('opens on an empty line when nothing was typed', () => {
      const emailBox = composer()
      clickReply(received, 'Reply', emailBox)
      expect(emailBox.inserted).toEqual([
        { at: 0, content: { type: 'paragraph' } },
      ])
    })
  })
})
