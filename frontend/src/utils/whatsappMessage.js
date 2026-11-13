import { sanitizeHTML } from '@/utils'

/** Enter on an empty or blank composer sends nothing: Meta refuses an empty body. */
export function canSendMessage(content) {
  return Boolean(content?.trim())
}

function escapeHTML(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// Private-use characters that stand in for a code span while the rest of the
// message is formatted. They are removed from the input first, so a message
// cannot carry a stand-in of its own.
const CODE_OPEN = ''
const CODE_CLOSE = ''
const STAND_INS = /[]/g

// WhatsApp formats `*bold*`, `_italic_` and `~strike~` only when the pair
// hugs its text and sits at the edges of a word: the opening marker follows
// the start of the line or something that is not a letter or digit, the
// closing one is followed by the same, and neither touches a space on the
// inside. Without that, `quote_final_v2.pdf` is italic and "2 * 3 * 4" bold.
// No lookbehind: Safari before 16.4 refuses to parse the whole file.
function pair(marker, tag) {
  const m = marker === '*' ? '\\*' : marker
  const pattern = new RegExp(
    `(^|[^\\p{L}\\p{N}${m}])${m}(?=\\S)([^\\n]*?\\S)${m}(?![\\p{L}\\p{N}])`,
    'gu',
  )
  return (text) => text.replace(pattern, `$1<${tag}>$2</${tag}>`)
}
const INLINE = [pair('_', 'i'), pair('*', 'b'), pair('~', 's')]
const inline = (text) => INLINE.reduce((out, format) => format(out), text)

/**
 * WhatsApp's markup as HTML. A message is text a stranger typed, so it is
 * escaped first: sanitizing alone keeps <img> and <a>, which would load a
 * tracker in the rep's browser and put a disguised link in the thread.
 *
 * Everything written after the escape is one of a fixed set of tags around
 * text that is already escaped, and no rule removes a character the sender
 * typed other than the markers themselves. Quotes and bullets count only at
 * the start of a line, as they do in WhatsApp; a numbered line ("1. Item",
 * and so "order 4521. Please") is left as the sender wrote it.
 */
export function formatWhatsAppMessage(message) {
  if (!message) return ''
  message = escapeHTML(String(message).replace(STAND_INS, ''))

  // ```block``` and `inline` code: taken out so nothing inside is formatted
  const code = []
  const hold = (_, block, span) =>
    CODE_OPEN + (code.push(block ?? span) - 1) + CODE_CLOSE
  message = message.replace(/```([\s\S]+?)```|`([^`\n]+)`/g, hold)

  const lines = message.split('\n').map((line) => {
    const quote = line.match(/^&gt; (.*)$/)
    if (quote) return `<blockquote>${inline(quote[1])}</blockquote>`
    const bullet = line.match(/^[*-] (\S.*)$/)
    if (bullet) return `<li>${inline(bullet[1])}</li>`
    return inline(line)
  })
  // a list item ends its own line; every other line break is a <br>
  message = lines
    .map((line, i) =>
      i < lines.length - 1 && !line.startsWith('<li>') ? line + '<br>' : line,
    )
    .join('')

  message = message.replace(
    /(\d+)/g,
    (_, i) => `<code>${code[i].replace(/\n/g, '<br>')}</code>`,
  )

  return sanitizeHTML(message)
}
