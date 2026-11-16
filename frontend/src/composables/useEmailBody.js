import { call } from 'frappe-ui'
import {
  cachedEmailBody,
  emailBodyOwner,
  forgetEmailBodies,
  pendingEmailBody,
  rememberEmailBody,
  trackPendingEmailBody,
} from '@/utils/emailBodyCache'

// The timeline carries each email's snippet, not its body (an Outlook thread is
// tens of KB of html, and a page of them was megabytes on every reload). Bodies
// are fetched when an email is opened and kept in utils/emailBodyCache, by
// Communication name and for the logged-in user only, so opening it again --
// or the reload after a comment -- does not fetch it twice.

export { cachedEmailBody, forgetEmailBodies, rememberEmailBody }

/** The sanitised body of one timeline email; one request however often asked. */
export function fetchEmailBody(name) {
  const cached = cachedEmailBody(name)
  if (cached !== undefined) return Promise.resolve(cached)
  const inFlight = pendingEmailBody(name)
  if (inFlight) return inFlight
  const user = emailBodyOwner()
  const request = call('crm.api.activities.get_email_body', { name }).then(
    (result) => {
      const content = result?.content ?? ''
      rememberEmailBody(name, content, user)
      return content
    },
  )
  trackPendingEmailBody(name, request)
  return request
}

// Reply on a closed email waits for its body; the composer is one per page, so
// only the most recent Reply click may fill it.
let latestReply = 0

export function claimReply() {
  return ++latestReply
}

export function isLatestReply(ticket) {
  return ticket === latestReply
}
