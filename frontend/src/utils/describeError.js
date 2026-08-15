/**
 * Turn whatever a failed request threw into something a person can read —
 * pure, so it can be unit-tested against the real shapes Frappe sends.
 *
 * It feeds ErrorState.vue, which is its only consumer today.
 *
 * Deliberately returns no copy of its own: `kind` lets the caller pick a
 * translated sentence, and `message` is only ever text the server actually
 * wrote for a human. That keeps every user-visible string inside a `__()` in
 * the component, where the i18n extractor can see it.
 */

const ENTITIES = {
  '&amp;': '&',
  '&lt;': '<',
  '&gt;': '>',
  '&quot;': '"',
  '&#39;': "'",
  '&nbsp;': ' ',
}

/* Frappe throws messages as HTML fragments (`<b>Not permitted</b>`). They are
   rendered as plain text here, never as markup — an error message is the last
   place to hand the server an HTML injection. */
function toPlainText(value) {
  if (value === null || value === undefined) return ''
  return String(value)
    .replace(/<br\s*\/?>/gi, ' ')
    .replace(/<[^>]*>/g, '')
    .replace(/&amp;|&lt;|&gt;|&quot;|&#39;|&nbsp;/g, (m) => ENTITIES[m])
    .replace(/\s+/g, ' ')
    .trim()
}

/* `_server_messages` is a JSON string holding an array of JSON strings, each
   an object with a `message`. Any layer of that can be malformed. */
function parseServerMessages(raw) {
  let entries
  try {
    entries = JSON.parse(raw)
  } catch {
    return [raw]
  }
  if (!Array.isArray(entries)) return [raw]

  return entries.map((entry) => {
    if (typeof entry !== 'string') return entry?.message ?? entry
    try {
      const parsed = JSON.parse(entry)
      return parsed?.message ?? entry
    } catch {
      return entry
    }
  })
}

function humanMessages(error) {
  const found = []
  if (Array.isArray(error.messages)) found.push(...error.messages)
  else if (typeof error.messages === 'string') found.push(error.messages)
  if (typeof error._server_messages === 'string') {
    found.push(...parseServerMessages(error._server_messages))
  }
  return found.map(toPlainText).filter(Boolean)
}

function statusOf(error) {
  const status = Number(
    error.status ??
      error.statusCode ??
      error.httpStatus ??
      error.response?.status,
  )
  return Number.isFinite(status) ? status : null
}

/* A fetch that never reached the server rejects with a TypeError whose message
   is browser-specific: "Failed to fetch" (Chrome), "NetworkError when
   attempting to fetch resource" (Firefox), "Load failed" (Safari). */
function isOffline(error, status) {
  if (status === 0 || error.code === 'ERR_NETWORK') return true
  const message = String(error.message || '')
  return (
    error.name === 'TypeError' &&
    /fetch|network|load failed|connection/i.test(message)
  )
}

function classify(error) {
  const status = statusOf(error)
  const excType = String(error.exc_type || error.excType || '')

  if (isOffline(error, status)) return 'offline'
  if (/PermissionError|AuthenticationError/i.test(excType)) return 'permission'
  if (status === 401 || status === 403) return 'permission'
  if (/DoesNotExistError|NotFound/i.test(excType) || status === 404)
    return 'notfound'
  if ((status !== null && status >= 500) || excType) return 'server'
  return 'unknown'
}

/* frappe-ui hands the raw throw straight through, but some call paths wrap it
   one level deeper as `{ error: <the real thing> }`. */
function unwrap(error) {
  const inner = error.error
  if (!inner || inner === error) return error
  if (typeof inner === 'string') return { ...error, message: inner }
  if (typeof inner === 'object' && !error.messages && !error._server_messages) {
    return inner
  }
  return error
}

/**
 * @param {unknown} error Anything a rejected resource produced.
 * @returns {{kind: string, message: string, detail: string}}
 *   `kind` is one of none | offline | permission | notfound | server | unknown
 *   and selects the caller's fallback sentence. `message` is the server's own
 *   human-readable text, or '' when it wrote none. `detail` is the raw
 *   diagnostic — traceback and all — for the disclosure, never for the face.
 */
export function describeError(error) {
  if (!error) return { kind: 'none', message: '', detail: '' }
  if (typeof error === 'string') {
    const message = toPlainText(error)
    return { kind: message ? 'unknown' : 'none', message, detail: '' }
  }
  if (typeof error !== 'object') {
    return { kind: 'unknown', message: toPlainText(error), detail: '' }
  }

  const source = unwrap(error)
  const messages = humanMessages(source)
  const kind = classify(source)
  const status = statusOf(source)
  const raw = toPlainText(source.message)

  /* A transport-level message ("Failed to fetch", "Internal Server Error") is
     noise in the face — the `kind` sentence says it better. Only text the
     server wrote for a human is promoted. */
  const message = messages[0] || (kind === 'unknown' ? raw : '')

  /* One trace, in order of usefulness: Frappe's own server traceback beats a
     browser stack that only shows the fetch call site. */
  const trace = String(source.exc || source.exception || source.stack || '')

  const detail = [
    source.exc_type || source.excType,
    status !== null ? `HTTP ${status}` : null,
    // A JS stack already opens with "TypeError: Failed to fetch"; printing the
    // message again above it is just noise.
    raw && raw !== message && !trace.includes(raw) ? raw : null,
    ...messages.slice(message === messages[0] ? 1 : 0),
    trace,
  ]
    .filter(Boolean)
    .map((line) => String(line).trim())
    .join('\n')
    .trim()

  return { kind, message, detail }
}
