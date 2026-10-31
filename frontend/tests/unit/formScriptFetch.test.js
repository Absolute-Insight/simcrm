import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * getScript runs for every useDocument call -- each rendered field, each
 * sub-document of a record page -- and decides whether to fetch the doctype's
 * CRM Form Scripts. Its guard read `scripts.loading`, which a list resource
 * does not have, and the "already fetched" marker was only written when a
 * script existed, so a doctype with none re-requested the list on every call:
 * about 19 parallel requests for a Lead's Data tab. Real frappe-ui list
 * resources here; only the server is faked.
 */
vi.mock('frappe-ui', async () => {
  const { createListResource } = await import(
    '../../node_modules/frappe-ui/src/resources/listResource.js'
  )
  const { setConfig } = await import(
    '../../node_modules/frappe-ui/src/utils/config.ts'
  )
  return {
    createListResource,
    setConfig,
    call: vi.fn(),
    toast: { error() {}, success() {} },
  }
})
vi.mock('@/stores/global', () => ({ globalStore: () => ({}) }))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({ doctypesMeta: {} }) }))
vi.mock('@/utils/renderFieldLayoutDialog', () => ({
  renderFieldLayoutDialog: () => {},
}))
vi.mock('@/router', () => ({ default: {} }))

import { setConfig } from 'frappe-ui'
import { getScript } from '@/data/script'

const settle = () => new Promise((r) => setTimeout(r, 0))
let requests
let respond

beforeEach(() => {
  requests = []
  respond = () => []
  setConfig('resourceFetcher', async ({ params = {} }) => {
    requests.push(params.filters?.dt)
    return respond(params)
  })
})

describe('getScript', () => {
  it('fetches a doctype with no Form Script once, not once per field', async () => {
    getScript('CRM Organization') // the record page
    getScript('CRM Organization') // a field mounted in the same tick
    await settle()
    getScript('CRM Organization') // the next record of that doctype
    getScript('CRM Organization')
    await settle()

    expect(requests).toEqual(['CRM Organization'])
  })

  it('asks again after a failed fetch', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    respond = () => {
      throw new Error('502 Bad Gateway')
    }
    getScript('CRM Task')
    await settle()
    respond = () => []
    getScript('CRM Task')
    await settle()
    getScript('CRM Task')
    await settle()

    expect(requests).toEqual(['CRM Task', 'CRM Task'])
  })

  it('still loads the scripts a doctype has', async () => {
    respond = () => [
      {
        name: 'Deal Form',
        dt: 'CRM Deal',
        view: 'Form',
        script: 'class CRMDeal {}',
      },
    ]
    const { scripts } = getScript('CRM Deal')
    await settle()
    getScript('CRM Deal')
    await settle()

    expect(requests).toEqual(['CRM Deal'])
    expect(scripts.data?.map((s) => s.name)).toEqual(['Deal Form'])
  })
})
