import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '../mount.js'
import { failure, field, flush } from './standIns.js'

// frappe-ui's real list resource: it keeps loading and error on `.list`, and
// reading them off the resource itself is the defect.
const backend = vi.hoisted(() => ({ handlers: {}, log: [], toasts: [] }))
vi.mock('frappe-ui', async (importOriginal) =>
  (await import('./standIns.js')).frappeUi(importOriginal, backend),
)
vi.mock('@/components/ui/ConfirmDialog.vue', () => ({
  default: { render: () => null },
}))

const { default: ReportDigests } = await import(
  '@/components/Settings/ReportDigests.vue'
)

const DIGEST = {
  name: 1,
  report: 'pipeline_by_stage',
  frequency: 'Weekly',
  enabled: 1,
  recipients: 'mgr@x.test',
}
let list
beforeEach(() => {
  backend.log.length = 0
  backend.handlers = {
    'crm.api.reports.list_reports': () => [
      { name: 'pipeline_by_stage', title: 'Pipeline by stage' },
    ],
    'frappe.client.get_list': () => list(),
  }
})

describe('Report Digests list states', () => {
  it('says it is loading while the list is in flight, not that there are none', async () => {
    let answer
    list = () => new Promise((resolve) => (answer = resolve))
    const { el } = mount(ReportDigests)
    await flush()
    expect(el.textContent).not.toContain('No digests yet')
    expect(el.querySelector('[aria-label="Loading digests"]')).not.toBeNull()
    answer([DIGEST])
    await flush()
    expect(el.textContent).toContain('Pipeline by stage')
  })

  it('says the list could not load, and retries it', async () => {
    list = () => Promise.reject(failure('Failed to fetch'))
    const { el } = mount(ReportDigests)
    await flush()
    expect(el.textContent).toContain('Could not load digests')
    expect(el.textContent).not.toContain('No digests yet')

    list = () => [DIGEST]
    const retry = [...el.querySelectorAll('button')].find((b) =>
      /try again|retry/i.test(b.textContent),
    )
    retry.click()
    await flush()
    expect(el.textContent).toContain('Pipeline by stage')
  })

  it('keeps the list on screen while a save reloads it', async () => {
    list = () => [DIGEST]
    const { el } = mount(ReportDigests)
    await flush()
    const row = [...el.querySelectorAll('button')].find((b) =>
      b.textContent.includes('Pipeline by stage'),
    )
    row.click()
    await flush()
    backend.handlers['frappe.client.set_value'] = () => ({ ...DIGEST })
    list = () => new Promise(() => {})
    field(el, 'Save digest').click()
    await flush()
    expect(
      backend.log.filter((r) => r.url === 'frappe.client.get_list'),
    ).toHaveLength(2)
    // the row's own summary, which only the list renders
    expect(el.textContent).toContain('Weekly · 1 recipients')
  })
})
