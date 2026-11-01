import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// Each list resource starts empty, the way a cold page load sees it; a test
// fills one in by calling its transform, as frappe-ui would on arrival.
const resources = {}
vi.mock('frappe-ui', () => ({
  createListResource: (opts) => {
    const resource = { data: [], ...opts }
    resources[opts.doctype] = resource
    return resource
  },
}))
vi.mock('@framework/ui/telemetry', () => ({
  useTelemetry: () => ({ capture: () => {} }),
}))

const { statusesStore } = await import('@/stores/statuses')

function arrive(doctype, rows) {
  const resource = resources[doctype]
  resource.data = resource.transform(rows)
}

describe('statuses store before the lists load', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('gives a colourless stand-in instead of undefined', () => {
    const { getLeadStatus, getDealStatus } = statusesStore()
    expect(getLeadStatus('New').color).toBe('')
    expect(getDealStatus('Won').type).toBe('')
  })

  it('does not throw when asked for the default with nothing loaded', () => {
    const { getLeadStatus, getDealStatus, getCommunicationStatus } =
      statusesStore()
    expect(() => getLeadStatus()).not.toThrow()
    expect(() => getDealStatus(undefined)).not.toThrow()
    expect(() => getCommunicationStatus('')).not.toThrow()
  })

  it('returns the real status once its list arrives', () => {
    const { getDealStatus, getCommunicationStatus } = statusesStore()
    arrive('CRM Deal Status', [{ name: 'Lost', color: 'red', type: 'Lost' }])
    arrive('CRM Communication Status', [{ name: 'Replied' }])
    expect(getDealStatus('Lost').type).toBe('Lost')
    expect(getDealStatus('Lost').color).not.toBe('')
    expect(getDealStatus().name).toBe('Lost')
    expect(getCommunicationStatus('Replied').name).toBe('Replied')
  })
})
