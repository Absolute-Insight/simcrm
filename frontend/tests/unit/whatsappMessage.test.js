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

/** The elements the browser makes of `html`, in document order. */
function elementsOf(html) {
  const box = document.createElement('div')
  box.innerHTML = html
  return [...box.querySelectorAll('*')]
}

/** What a reader sees: the text, with a line break where the markup makes one. */
function shownText(html) {
  const box = document.createElement('div')
  box.innerHTML = html
  let text = ''
  const walk = (node) => {
    for (const child of node.childNodes) {
      if (child.nodeType === 3) text += child.textContent
      else if (child.nodeName === 'BR') {
        // the break after a quote is the quote's own line end
        if (child.previousSibling?.nodeName !== 'BLOCKQUOTE') text += '\n'
      } else {
        walk(child)
        if (['LI', 'BLOCKQUOTE'].includes(child.nodeName)) text += '\n'
      }
    }
  }
  walk(box)
  return text
}

// the private-use characters the formatter uses as stand-ins
const OPEN = String.fromCharCode(0xe000)
const CLOSE = String.fromCharCode(0xe001)
const STAND_IN = new RegExp(`[${OPEN}${CLOSE}]`)

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
    expect(shownText(formatWhatsAppMessage(message))).toBe(
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

  it('leaves a link exactly as it was sent', () => {
    for (const message of [
      'https://x.com/_foo_/bar',
      'see https://files.example.com/~user/~files~/a_b_c.pdf today',
      'www.example.com/*new*/_list_',
      'HTTP://EXAMPLE.COM/_A_',
      'two: https://a.test/_x_ and https://b.test/~y~',
    ]) {
      expect(formatWhatsAppMessage(message)).toBe(message)
    }
    expect(formatWhatsAppMessage('https://x.com/?a=1&b=<2>')).toBe(
      'https://x.com/?a=1&amp;b=&lt;2&gt;',
    )
  })

  it('still formats around a link, and a pair that wraps one', () => {
    expect(formatWhatsAppMessage('*read* https://x.com/_a_ _now_')).toBe(
      '<b>read</b> https://x.com/_a_ <i>now</i>',
    )
    expect(formatWhatsAppMessage('*https://x.com/a_b*')).toBe(
      '<b>https://x.com/a_b</b>',
    )
    expect(formatWhatsAppMessage('(see https://x.com/a_b_c).')).toBe(
      '(see https://x.com/a_b_c).',
    )
    // not a link: no scheme, so it is text like any other
    expect(formatWhatsAppMessage('the _httpd_ log')).toBe(
      'the <i>httpd</i> log',
    )
  })

  it('does not make half a pair of a doubled marker', () => {
    for (const plain of ['**bold**', '__x__', '~~gone~~', '***', '** a **']) {
      expect(formatWhatsAppMessage(plain)).toBe(plain)
    }
  })

  it('never writes tags that cross', () => {
    // the pair that opens first wins; one that would close outside it is text
    expect(formatWhatsAppMessage('*a _b* c_')).toBe('<b>a _b</b> c_')
    expect(formatWhatsAppMessage('_a *b_ c*')).toBe('<i>a *b</i> c*')
    expect(formatWhatsAppMessage('~a *b* c~ *d*')).toBe(
      '<s>a <b>b</b> c</s> <b>d</b>',
    )
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
      OPEN,
      '0',
      CLOSE,
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
      for (const element of elementsOf(html)) {
        expect(['I', 'B', 'S', 'CODE', 'LI', 'BLOCKQUOTE', 'BR']).toContain(
          element.nodeName,
        )
        expect(element.attributes).toHaveLength(0)
      }
      // what the browser builds from it writes back the same: nothing is
      // left open, closed twice or closed out of order
      const box = document.createElement('div')
      box.innerHTML = html
      expect(box.innerHTML).toBe(html)
      expect(html).not.toMatch(STAND_IN)
    }
  })

  it("cannot be handed a code stand-in of the sender's own", () => {
    expect(formatWhatsAppMessage(`${OPEN}0${CLOSE} \`x\``)).toBe(
      '0 <code>x</code>',
    )
  })

  it('takes a message that is not a string', () => {
    expect(formatWhatsAppMessage(4521)).toBe('4521')
  })

  it('takes an empty message', () => {
    expect(formatWhatsAppMessage(null)).toBe('')
    expect(formatWhatsAppMessage('')).toBe('')
  })
})
