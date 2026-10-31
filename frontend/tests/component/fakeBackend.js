import { setConfig } from 'frappe-ui'

/**
 * Route frappe-ui's resources (createResource, createListResource and the
 * list resource's insert/setValue/delete) to in-memory handlers keyed by
 * method, so a component test runs the real resource layer -- pagination,
 * onSuccess/onError ordering -- against answers the test controls.
 *
 *   const backend = fakeBackend()
 *   backend.handlers['frappe.client.get_list'] = (params) => rows
 *
 * A handler that throws is a refused request. `log` records every call.
 */
export function fakeBackend() {
  const handlers = {}
  const log = []
  setConfig('resourceFetcher', async ({ url, params }) => {
    log.push({ url, params: JSON.parse(JSON.stringify(params ?? {})) })
    const handler = handlers[url]
    if (!handler) throw new Error(`no fake handler for ${url}`)
    return handler(params ?? {})
  })
  return { handlers, log }
}

/** What frappeRequest throws for a refused call: messages, exc_type, and a
 *  `message` that is the URL and exception class, not the reason. */
export function frappeError(message, url = 'frappe.client.set_value') {
  const error = new Error(`/api/method/${url} ValidationError`)
  error.messages = [message]
  error.exc_type = 'ValidationError'
  return error
}
