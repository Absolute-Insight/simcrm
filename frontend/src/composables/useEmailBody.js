import { call } from 'frappe-ui'

// The timeline carries each email's snippet, not its body (an Outlook thread is
// tens of KB of html, and a page of them was megabytes on every reload). Bodies
// are fetched when an email is opened and kept here, by Communication name, so
// opening it again -- or the reload after a comment -- does not fetch it twice.
// Bounded: a rep reading through a long thread holds the most recent ones.
const MAX_BODIES = 40

const bodies = new Map()
const pending = new Map()

export function rememberEmailBody(name, content) {
  if (!name || typeof content !== 'string') return
  bodies.delete(name)
  bodies.set(name, content)
  while (bodies.size > MAX_BODIES) bodies.delete(bodies.keys().next().value)
}

export function cachedEmailBody(name) {
  return bodies.get(name)
}

/** The sanitised body of one timeline email; one request however often asked. */
export function fetchEmailBody(name) {
  if (bodies.has(name)) return Promise.resolve(bodies.get(name))
  if (pending.has(name)) return pending.get(name)
  const request = call('crm.api.activities.get_email_body', { name })
    .then((result) => {
      rememberEmailBody(name, result?.content ?? '')
      return bodies.get(name)
    })
    .finally(() => pending.delete(name))
  pending.set(name, request)
  return request
}

export function forgetEmailBodies() {
  bodies.clear()
  pending.clear()
}
