import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { setConfig } from 'frappe-ui'
import { mount } from './mount.js'

// A refused record, through the real useDocument and frappe-ui's real
// resources: each read rejects, and useDocument starts them itself, so nothing
// else can catch what they reject with.
vi.mock('@/data/script', () => ({
  getScript: () => ({ setupScript: async () => null, scripts: { data: [] } }),
}))
vi.mock('@/stores/global', () => ({ globalStore: () => ({}) }))
vi.mock('@/stores/meta', () => ({
  getMeta: () => ({ getFields: () => [] }),
}))
vi.mock('@/composables/useAttachments', () => ({
  useAttachments: () => ({}),
}))

const { useDocument } = await import('@/data/document')

const REFUSED = Object.assign(new Error('refused'), {
  exc_type: 'PermissionError',
  messages: ['Not allowed via controller permission check'],
})

describe('useDocument on a refused record', () => {
  const rejections = []
  const onRejection = (reason) => rejections.push(reason)

  beforeEach(() => {
    rejections.length = 0
    process.on('unhandledRejection', onRejection)
    setConfig('resourceFetcher', async () => {
      throw REFUSED
    })
  })
  afterEach(() => {
    process.off('unhandledRejection', onRejection)
  })

  it('reports it on `error`, and leaves no rejection unhandled', async () => {
    let error
    mount({
      setup() {
        ;({ error } = useDocument('CRM Deal', 'CRM-DEAL-REFUSED'))
        return () => h('div')
      },
    })
    await new Promise((r) => setTimeout(r, 20))

    expect(error.value).toBe(REFUSED)
    expect(rejections).toEqual([])
  })
})
