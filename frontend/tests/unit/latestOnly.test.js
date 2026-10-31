import { describe, expect, it, vi } from 'vitest'

const config = vi.hoisted(() => ({}))
vi.mock('frappe-ui', () => ({
  getConfig: (key) => config[key],
  frappeRequest: () => Promise.resolve('frappeRequest'),
}))

import { latestOnly } from '@/utils/latestOnly'

/** A transport whose requests answer when, and in the order, the test says. */
function deferredTransport() {
  const sent = []
  const send = (options) =>
    new Promise((resolve, reject) => sent.push({ options, resolve, reject }))
  return { sent, send }
}

const settled = (promise) =>
  promise.then(
    (value) => ({ value }),
    (error) => ({ error }),
  )

describe('latestOnly', () => {
  it('passes a lone request straight through', async () => {
    const { sent, send } = deferredTransport()
    const fetch = latestOnly(send)
    const answer = fetch({ params: { from: 'a' } })
    sent[0].resolve('A')
    expect(await answer).toBe('A')
  })

  it('drops an earlier answer that lands after a later request', async () => {
    const { sent, send } = deferredTransport()
    const fetch = latestOnly(send)
    const ninety = settled(fetch({ params: { days: 90 } }))
    const seven = settled(fetch({ params: { days: 7 } }))

    sent[1].resolve('7 days')
    sent[0].resolve('90 days') // the slow query lands last

    expect(await seven).toEqual({ value: '7 days' })
    const dropped = await ninety
    expect(dropped.value).toBeUndefined()
    // createResource stops quietly on an AbortError: no data, no onSuccess
    expect(dropped.error.name).toBe('AbortError')
  })

  it('holds a superseded answer until the newer request settles', async () => {
    const { sent, send } = deferredTransport()
    const fetch = latestOnly(send)
    let droppedAt = null
    fetch({}).catch(() => (droppedAt = performance.now()))
    const newer = fetch({})

    sent[0].resolve('old') // lands first, while the newer one is still out
    await new Promise((r) => setTimeout(r, 5))
    // still pending: rejecting now would end the resource's loading state
    // with the old figures on screen under the new label
    expect(droppedAt).toBeNull()

    sent[1].resolve('new')
    expect(await newer).toBe('new')
    await new Promise((r) => setTimeout(r, 0))
    expect(droppedAt).not.toBeNull()
  })

  it('follows a request that is itself superseded while waiting', async () => {
    const { sent, send } = deferredTransport()
    const fetch = latestOnly(send)
    const first = settled(fetch({}))
    fetch({}).catch(() => {})
    sent[0].resolve('first')
    const third = fetch({})
    sent[1].resolve('second')
    sent[2].resolve('third')
    expect(await third).toBe('third')
    expect((await first).error.name).toBe('AbortError')
  })

  it("drops a superseded request's failure as well", async () => {
    const { sent, send } = deferredTransport()
    const fetch = latestOnly(send)
    const older = settled(fetch({}))
    const newer = fetch({})
    sent[0].reject(new Error('timeout'))
    sent[1].resolve('fresh')
    expect(await newer).toBe('fresh')
    expect((await older).error.name).toBe('AbortError')
  })

  it("lets the latest request's own failure through", async () => {
    const { sent, send } = deferredTransport()
    const answer = settled(latestOnly(send)({}))
    const failure = new Error('403')
    sent[0].reject(failure)
    expect((await answer).error).toBe(failure)
  })

  it("sends through the app's configured resourceFetcher by default", async () => {
    config.resourceFetcher = vi.fn(() => Promise.resolve('configured'))
    expect(await latestOnly()({ url: 'x' })).toBe('configured')
    expect(config.resourceFetcher).toHaveBeenCalledWith({ url: 'x' })
    delete config.resourceFetcher
    expect(await latestOnly()({ url: 'x' })).toBe('frappeRequest')
  })
})
