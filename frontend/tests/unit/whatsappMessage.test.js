import { describe, expect, it, vi } from 'vitest'

import { canSendMessage, formatWhatsAppMessage } from '@/utils/whatsappMessage'

// DOMPurify under the test DOM drops nodes a browser keeps, so this pins what
// goes into it: an identity sanitizer is the harder test for the escaping.
vi.mock('@/utils', () => ({ sanitizeHTML: (html) => html }))

describe('canSendMessage', () => {
  it('refuses nothing, blanks and newlines', () => {
    for (const content of ['', '   ', '\n\n', null, undefined]) {
      expect(canSendMessage(content)).toBe(false)
    }
  })

  it('accepts text', () => {
    expect(canSendMessage(' hi ')).toBe(true)
  })
})

describe('formatWhatsAppMessage', () => {
  it("shows a stranger's markup as text", () => {
    const out = formatWhatsAppMessage(
      '<img src="https://evil.test/track.png"> <a href="https://evil.test">click</a>',
    )
    expect(out).not.toContain('<img')
    expect(out).not.toContain('<a ')
    expect(out).toContain('&lt;img')
  })

  it('still applies WhatsApp formatting', () => {
    expect(formatWhatsAppMessage('*bold*')).toContain('<b>bold</b>')
    expect(formatWhatsAppMessage('> quoted')).toContain(
      '<blockquote>quoted</blockquote>',
    )
    expect(formatWhatsAppMessage('a\nb')).toContain('<br>')
  })

  it('takes an empty message', () => {
    expect(formatWhatsAppMessage(null)).toBe('')
    expect(formatWhatsAppMessage('')).toBe('')
  })
})
