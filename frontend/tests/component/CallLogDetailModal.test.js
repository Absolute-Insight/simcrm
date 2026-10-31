import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h, reactive } from 'vue'
import { setConfig } from 'frappe-ui'
import { mount } from './mount.js'
import { flush, modalStubs, translation } from './stubs.js'
import CallLogDetailModal from '@/components/Modals/CallLogDetailModal.vue'

// The real useDocument on frappe-ui's real createResource and
// createDocumentResource; the fetcher counts every request that reaches the
// server. The CRM Call Log Form Script is one controller with onCreateLead.
const S = vi.hoisted(() => ({ requests: [], order: [] }))

vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  call: (method) => {
    S.order.push(method)
    return Promise.resolve('LEAD-1')
  },
  toast: { error() {}, success() {} },
}))
vi.mock('reka-ui', async (importOriginal) => {
  const { h } = await import('vue')
  const pass = (name) => ({
    name,
    render() {
      return h('div', this.$slots.default?.())
    },
  })
  return {
    ...(await importOriginal()),
    DialogTitle: pass('DialogTitle'),
    DialogDescription: pass('DialogDescription'),
    VisuallyHidden: pass('VisuallyHidden'),
  }
})
vi.mock('@/utils/callLog', () => ({ getCallLogDetail: (key, d) => d[key] }))
vi.mock('@/components/FadedScrollableDiv.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/composables/doctypeModal', () => ({
  useDoctypeModal: () => ({ showModal() {} }),
}))
vi.mock('@/data/script', () => ({
  getScript: () => ({
    scripts: {},
    setupScript: async () => [
      {
        _className: 'CRMCallLog',
        onCreateLead: () => S.order.push('onCreateLead'),
      },
    ],
  }),
}))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog() {}, $socket: null, makeCall() {} }),
}))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({}) }))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: (name) => ({ name, full_name: name }) }),
}))
vi.mock('@/composables/useAttachments', () => ({
  useAttachments: () => ({ trackOldFile() {}, processPendingDeletions() {} }),
}))
vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal()),
  useRouter: () => ({ push() {} }),
}))

setConfig('resourceFetcher', (options) => {
  S.requests.push(options.url)
  const answers = {
    'frappe.client.get': { doctype: 'CRM Call Log', name: options.params.name },
    'crm.api.doc.get_assigned_users': [],
    'frappe.client.get_doc_permissions': { permissions: {} },
  }
  return Promise.resolve(answers[options.url] ?? {})
})

// As getCallLogDetail (stubbed to read the key) would render it.
const callLogData = (name) => ({
  name,
  type: { label: 'Incoming', icon: 'lucide-phone-incoming' },
  creation: { label: 'today' },
  duration: { label: '1m' },
  status: { label: 'Completed', color: 'green' },
  caller: { label: 'Ann', image: null },
  receiver: { label: 'Ben', image: null },
  _notes: [],
  _tasks: [],
})

beforeEach(() => {
  S.requests.length = 0
  S.order.length = 0
})

describe('CallLogDetailModal', () => {
  it('a timeline of closed call modals makes no requests of its own', async () => {
    // CallArea mounts one closed modal per call, with its own get_call_log
    // resource; the responses arrive and nobody opens a modal.
    const callLogs = Array.from({ length: 12 }, () =>
      reactive({ data: null, reload() {} }),
    )
    const w = mount(
      {
        render: () =>
          h(
            'div',
            callLogs.map((callLog) =>
              h(CallLogDetailModal, { modelValue: false, callLog }),
            ),
          ),
      },
      { stubs: modalStubs, plugins: [translation] },
    )
    await flush()
    callLogs.forEach((cl, i) => (cl.data = callLogData(`CL-${i}`)))
    await flush()
    expect(S.requests).toEqual([])
    w.unmount()
  })

  it("Create Lead still runs the Form Script's onCreateLead first", async () => {
    const callLog = reactive({ data: callLogData('CL-99'), reload() {} })
    const w = mount(CallLogDetailModal, {
      props: { modelValue: true, callLog },
      stubs: modalStubs,
      plugins: [translation],
    })
    await flush()
    w.el.querySelector('button[data-label="Create Lead"]').click()
    await flush(12)
    expect(S.order).toEqual([
      'onCreateLead',
      'crm.fcrm.doctype.crm_call_log.crm_call_log.create_lead_from_call_log',
    ])
    w.unmount()
  })
})
