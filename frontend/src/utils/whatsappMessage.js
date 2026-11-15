import { sanitizeHTML } from '@/utils'

/** Enter on an empty or blank composer sends nothing: Meta refuses an empty body. */
export function canSendMessage(content) {
  return Boolean(content?.trim())
}

function escapeHTML(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// Private-use characters that stand in for a span the formatter must not look
// inside -- code, a link -- while the rest of the message is formatted. They
// are removed from the input first, so a message cannot carry a stand-in of
// its own.
const HELD_OPEN = String.fromCharCode(0xe000)
const HELD_CLOSE = String.fromCharCode(0xe001)
const STAND_INS = new RegExp(`[${HELD_OPEN}${HELD_CLOSE}]`, 'g')
const HELD = new RegExp(`${HELD_OPEN}(\\d+)${HELD_CLOSE}`, 'g')

// ```block``` and `inline` code.
const CODE = /```([\s\S]+?)```|`([^`\n]+)`/g
// A link, as typed: http(s):// or www. up to the next space. An underscore or
// tilde in a path is part of the address, not markup -- formatted, the link a
// rep copies out of the thread is not the one that was sent. It stops at a
// stand-in as well: code typed straight after a link is its own span, and a
// stand-in swallowed into a held link would never be put back.
const URL = new RegExp(
  `\\b(?:https?:\\/\\/|www\\.)[^\\s${HELD_OPEN}${HELD_CLOSE}]+`,
  'gi',
)
// ...less what sentence punctuation or a closing marker left on its end.
const URL_TAIL = new Set('.,;:!?)*_~')

/** `url` and the punctuation after it, split by walking back from the end. */
function splitLink(url) {
  let end = url.length
  while (end > 0 && URL_TAIL.has(url[end - 1])) end--
  return [url.slice(0, end), url.slice(end)]
}

const TAGS = { '*': 'b', _: 'i', '~': 's' }
const WORD = /[\p{L}\p{N}]/u
const isWord = (char) => char !== undefined && WORD.test(char)
const isSpace = (char) => char === undefined || /\s/.test(char)

/**
 * `*bold*`, `_italic_` and `~strike~` on one line of escaped text.
 *
 * WhatsApp formats a pair only when it hugs its text and sits at the edges of
 * a word: the opening marker follows the start of the line or something that
 * is not a letter or digit, the closing one is followed by the same, and
 * neither touches a space -- or another of itself -- on the inside. Without
 * that, `quote_final_v2.pdf` is italic, "2 * 3 * 4" bold and `**x**` half of
 * each.
 *
 * Read left to right, and a pair's inside is formatted on its own: a marker
 * that opens inside a pair and closes outside it (`*a _b* c_`) stays text, so
 * the tags written are always properly nested. Nothing written is read again.
 *
 * One pass over the line. Where each marker can close is worked out once, up
 * front, and each marker keeps its place in that list as the line is read --
 * looking ahead for a closer from every opener made a long line of openers
 * that never close (" *a *a *a ...") quadratic, seconds for a message of a
 * hundred kilobytes. A pair nests at most three deep, one per marker: the
 * inside of a pair holds no closer of its own marker.
 */
function inline(text) {
  const closers = { '*': [], _: [], '~': [] }
  for (let j = 1; j < text.length; j++) {
    const marker = text[j]
    if (
      TAGS[marker] &&
      !isSpace(text[j - 1]) &&
      text[j - 1] !== marker &&
      text[j + 1] !== marker &&
      !isWord(text[j + 1])
    ) {
      closers[marker].push(j)
    }
  }
  // per marker, the first closer not yet behind the reader
  const next = { '*': 0, _: 0, '~': 0 }

  const span = (start, end) => {
    let out = ''
    let from = start
    for (let i = start; i < end; i++) {
      const marker = text[i]
      if (!TAGS[marker]) continue
      const opens =
        !isWord(text[i - 1]) &&
        text[i - 1] !== marker &&
        !isSpace(text[i + 1]) &&
        text[i + 1] !== marker
      if (!opens) continue
      const places = closers[marker]
      let at = next[marker]
      while (at < places.length && places[at] < i + 2) at++
      next[marker] = at
      // none left, or the next one is outside the pair being read
      if (at === places.length || places[at] >= end) continue
      const close = places[at]
      const tag = TAGS[marker]
      out += `${text.slice(from, i)}<${tag}>${span(i + 1, close)}</${tag}>`
      from = close + 1
      i = close
    }
    return out + text.slice(from, end)
  }
  return span(0, text.length)
}

/**
 * WhatsApp's markup as HTML. A message is text a stranger typed, so it is
 * escaped first: sanitizing alone keeps <img> and <a>, which would load a
 * tracker in the rep's browser and put a disguised link in the thread.
 *
 * Everything written after the escape is one of a fixed set of tags around
 * text that is already escaped, and no rule removes a character the sender
 * typed other than the markers themselves. Quotes and bullets count only at
 * the start of a line, as they do in WhatsApp; a numbered line ("1. Item",
 * and so "order 4521. Please") is left as the sender wrote it, and so is a
 * link.
 */
export function formatWhatsAppMessage(message) {
  if (!message) return ''
  message = escapeHTML(String(message).replace(STAND_INS, ''))

  // Taken out so nothing inside is formatted, and put back at the end.
  const held = []
  const hold = (html) => HELD_OPEN + (held.push(html) - 1) + HELD_CLOSE
  message = message.replace(CODE, (_, block, span) =>
    hold(`<code>${(block ?? span).replace(/\n/g, '<br>')}</code>`),
  )
  message = message.replace(URL, (url) => {
    const [link, tail] = splitLink(url)
    return hold(link) + tail
  })

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

  // A stand-in holds only what was put there above: one pass, never nested.
  message = message.replace(HELD, (_, i) => held[i])

  return sanitizeHTML(message)
}
