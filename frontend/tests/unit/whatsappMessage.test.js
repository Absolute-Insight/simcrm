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

  it('keeps the numbers and words of an ordinary sentence', () => {
    for (const message of [
      'My order number is 4521. Please check it.',
      'Delivery in 5 - 10 days',
      'see quote_final_v2.pdf',
      'ref 12. 13. 14. done',
      '2 * 3 * 4 = 24',
      'R1500 ~ R1800, ~ 3 weeks',
      'snake_case and other_names stay',
      'a - b - c',
    ]) {
      expect(formatWhatsAppMessage(message)).toBe(message)
    }
  })

  it('never drops a character other than the markers', () => {
    const message =
      '1. First *item*\n2. Second _item_\n- a bullet\n* another\n> a ~quote~\nPO 77. Thanks'
    const text = formatWhatsAppMessage(message)
      .replace(/<\/blockquote><br>|<br>|<\/li>/g, '\n')
      .replace(/<[^>]*>/g, '')
    expect(text).toBe(
      '1. First item\n2. Second item\na bullet\nanother\na quote\nPO 77. Thanks',
    )
  })

  it('formats a pair only at the edges of a word', () => {
    expect(formatWhatsAppMessage('_italic_, *bold*. (~gone~)')).toBe(
      '<i>italic</i>, <b>bold</b>. (<s>gone</s>)',
    )
    expect(formatWhatsAppMessage('*_both_*')).toBe('<b><i>both</i></b>')
    expect(formatWhatsAppMessage('*two words* and *more*')).toBe(
      '<b>two words</b> and <b>more</b>',
    )
    // a marker that touches a space on the inside, or a letter on the outside
    for (const plain of [
      'x * not bold*',
      '*not bold *',
      'a*b*c',
      '5*4*3',
      '_a_b',
    ]) {
      expect(formatWhatsAppMessage(plain)).toBe(plain)
    }
    // a pair does not reach across lines
    expect(formatWhatsAppMessage('*a\nb*')).toBe('*a<br>b*')
  })

  it('makes a bullet only of a line that starts with one', () => {
    expect(formatWhatsAppMessage('- one\n- two\nthen')).toBe(
      '<li>one</li><li>two</li>then',
    )
    expect(formatWhatsAppMessage('* one *big* thing')).toBe(
      '<li>one <b>big</b> thing</li>',
    )
    expect(formatWhatsAppMessage('-5 degrees\n-')).toBe('-5 degrees<br>-')
  })

  it('leaves code as typed', () => {
    expect(formatWhatsAppMessage('run `npm_run_*all*` now')).toBe(
      'run <code>npm_run_*all*</code> now',
    )
    expect(formatWhatsAppMessage('```- a\n_b_```')).toBe(
      '<code>- a<br>_b_</code>',
    )
  })

  it('escapes markup wherever it sits in the formatting', () => {
    const attack = '<img src=x onerror=alert(1)>'
    const escaped = '&lt;img src=x onerror=alert(1)&gt;'
    for (const [message, html] of [
      [`*${attack}*`, `<b>${escaped}</b>`],
      [`_${attack}_`, `<i>${escaped}</i>`],
      [`~${attack}~`, `<s>${escaped}</s>`],
      [`\`${attack}\``, `<code>${escaped}</code>`],
      [`\`\`\`${attack}\`\`\``, `<code>${escaped}</code>`],
      [`- ${attack}`, `<li>${escaped}</li>`],
      [`> ${attack}`, `<blockquote>${escaped}</blockquote>`],
      [`1. ${attack}`, `1. ${escaped}`],
      [
        '<b onmouseover=alert(1)>*x*</b>',
        '&lt;b onmouseover=alert(1)&gt;<b>x</b>&lt;/b&gt;',
      ],
      [
        '&lt;script&gt; & <script>',
        '&amp;lt;script&amp;gt; &amp; &lt;script&gt;',
      ],
    ]) {
      expect(formatWhatsAppMessage(message)).toBe(html)
    }
  })

  it('writes only its own tags, whatever the message', () => {
    const pieces = [
      '<',
      '>',
      '&',
      '*',
      '_',
      '~',
      '`',
      '```',
      '- ',
      '> ',
      '\n',
      'a',
      ' ',
      '1. ',
      '',
      '0',
      '',
      '<script>',
      '"',
      "'",
    ]
    // a fixed walk through combinations of the pieces: no randomness in CI
    let seed = 7
    const next = () => (seed = (seed * 1103515245 + 12345) % 2147483648)
    for (let run = 0; run < 2000; run++) {
      let message = ''
      for (let n = 0; n < 12; n++) message += pieces[next() % pieces.length]
      const html = formatWhatsAppMessage(message)
      const tags = html.match(/<[^>]*>?/g) || []
      for (const tag of tags) {
        expect(tag).toMatch(/^<\/?(i|b|s|code|li|blockquote)>$|^<br>$/)
      }
      expect(html).not.toMatch(/[]/)
    }
  })

  it("cannot be handed a code stand-in of the sender's own", () => {
    expect(formatWhatsAppMessage('0 `x`')).toBe('0 <code>x</code>')
  })

  it('takes a message that is not a string', () => {
    expect(formatWhatsAppMessage(4521)).toBe('4521')
  })

  it('takes an empty message', () => {
    expect(formatWhatsAppMessage(null)).toBe('')
    expect(formatWhatsAppMessage('')).toBe('')
  })
})
