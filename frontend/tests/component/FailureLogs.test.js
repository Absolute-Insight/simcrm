import { describe, it, expect, vi } from 'vitest'
import { defineComponent, h, reactive } from 'vue'
import { fakeBackend, frappeError } from './fakeBackend.js'
import { flushPromises } from './flush.js'
import { mount } from './mount.js'

const { toast, captured } = vi.hoisted(() => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
  captured: {},
}))
vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  toast,
}))
vi.mock('frappe-ui/experimental', () => ({
  // the rows as buttons; ListView's own row click is a reka/table detail
  ListView: defineComponent({
    props: {
      rows: { type: Array, default: () => [] },
      options: { type: Object, default: () => ({}) },
    },
    setup: (props) => () =>
      h(
        'div',
        props.rows.map((row) =>
          h(
            'button',
            { onClick: () => props.options.onRowClick(row) },
            row.name,
          ),
        ),
      ),
  }),
}))
// The retry is a whitelisted method of the log's document resource; what is
// under test is the handler this pane gives it.
vi.mock('@/data/document', () => ({
  useDocument: (doctype, name, options) => {
    captured.retrySync = options.whitelistedMethods.retrySync
    return {
      document: reactive({
        doc: { name },
        retrySync: { loading: false, submit() {} },
      }),
    }
  },
}))

import { Button } from 'frappe-ui'
import FailureLogs from '@/components/Settings/LeadSyncing/FailureLogs.vue'

describe('FailureLogs Retry Sync (FE-132)', () => {
  it("toasts the server's reason, not the endpoint and exception class", async () => {
    const backend = fakeBackend()
    backend.handlers['frappe.client.get_list'] = () => [
      { name: 'FLSL-0001', type: 'Duplicate', lead_data: '{}', traceback: '' },
    ]
    const w = mount(FailureLogs, {
      props: { source: 'Website FB' },
      stubs: { Button },
    })
    await flushPromises()
    w.el.querySelector('button').click()
    await flushPromises()

    captured.retrySync.onError(
      frappeError(
        "Can't retry sync for this without source!",
        'run_doc_method',
      ),
    )
    expect(toast.error).toHaveBeenLastCalledWith(
      "Can't retry sync for this without source!",
    )
    captured.retrySync.onError(new TypeError('Failed to fetch'))
    expect(toast.error).toHaveBeenLastCalledWith('Error syncing lead')
  })
})
