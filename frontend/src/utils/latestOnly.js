import { frappeRequest, getConfig } from 'frappe-ui'

/**
 * A `resourceFetcher` that lets only a resource's most recent request answer.
 *
 * frappe-ui's createResource neither aborts nor discards an earlier request
 * when it fetches again, so whichever response lands *last* is the one it
 * keeps. Two quick filter changes whose first query is the slower one then
 * show the first selection's figures under the second one's label, with
 * nothing on screen to say so.
 *
 * Here a superseded response is dropped as an AbortError, which createResource
 * treats as a deliberate stop: its data, onSuccess and error are left alone.
 * It is dropped only once the request that replaced it has settled, so the
 * resource's `loading` stays on until the figures that match the label land.
 *
 * One per resource -- the guard is that resource's own request order:
 *
 *   createResource({ url, makeParams, resourceFetcher: latestOnly() })
 *
 * @param {Function} [fetcher] the transport; the app's configured
 *   `resourceFetcher` (main.js) by default, read per request.
 */
export function latestOnly(fetcher) {
  let latest = null

  async function superseded() {
    // whatever replaced this request may itself be replaced while it runs
    let awaited
    do {
      awaited = latest
      await awaited.catch(() => {})
    } while (awaited !== latest)
    throw Object.assign(new Error('Superseded by a newer request'), {
      name: 'AbortError',
    })
  }

  return async (options) => {
    const send = fetcher || getConfig('resourceFetcher') || frappeRequest
    const request = Promise.resolve(send(options))
    latest = request
    let data
    try {
      data = await request
    } catch (error) {
      if (request === latest) throw error
      return superseded()
    }
    return request === latest ? data : superseded()
  }
}
