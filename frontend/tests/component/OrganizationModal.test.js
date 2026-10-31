import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import { flush, modalStubs, translation } from './stubs.js'
import OrganizationModal from '@/components/Modals/OrganizationModal.vue'
import { useDocument } from '@/data/document'

// The real useDocument, so the session-wide 'CRM Organization' create buffer
// is the one the modal edits.
const { call } = vi.hoisted(() => ({ call: vi.fn() }))

vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  call,
  toast: { error() {}, success() {}, info() {}, warning() {} },
  createResource: (opts) => ({ data: null, fetch() {}, reload() {}, ...opts }),
  createDocumentResource: () => ({ doc: {}, save: { submit() {} } }),
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
vi.mock('vue-router', () => ({ useRouter: () => ({ push() {} }) }))
vi.mock('@/components/FieldLayout/FieldLayout.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ isManager: () => false }),
}))
vi.mock('@/data/script', () => ({
  getScript: () => ({ setupScript: async () => [], scripts: {} }),
}))
vi.mock('@/stores/global', () => ({ globalStore: () => ({}) }))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({}) }))
vi.mock('@/composables/useAttachments', () => ({
  useAttachments: () => ({ trackOldFile() {}, processPendingDeletions() {} }),
}))

const buffer = () => useDocument('CRM Organization').document

function open(props = {}) {
  return mount(OrganizationModal, {
    props: { modelValue: true, ...props },
    stubs: modalStubs,
    plugins: [translation],
  })
}

describe('OrganizationModal', () => {
  it('opens without the values of a create form that was closed unsaved', async () => {
    // Organizations -> Create; the rep types a website and an address, closes.
    const first = open()
    await flush()
    Object.assign(buffer().doc, {
      organization_name: 'Acme Valves',
      website: 'https://acme.example',
      address: 'Acme Valves-Billing',
    })
    first.unmount()

    // Later, a deal's organization field -> Create New "Beta Pumps".
    const second = open({
      data: { organization_name: 'Beta Pumps' },
      options: { redirect: false },
    })
    await flush()
    expect(buffer().doc).toEqual({
      doctype: 'CRM Organization',
      __newDocument: true,
      no_of_employees: '1-10',
      organization_name: 'Beta Pumps',
    })
    second.unmount()
  })

  it('leaves a fresh draft, not {}, after a successful create', async () => {
    const m = open({
      data: { organization_name: 'Gamma' },
      options: { redirect: false },
    })
    await flush()
    call.mockResolvedValueOnce({ name: 'Gamma' })
    await m.vm.$.setupState.createOrganization()
    await flush()
    expect(call).toHaveBeenCalledWith(
      'frappe.client.insert',
      { doc: expect.objectContaining({ organization_name: 'Gamma' }) },
      expect.anything(),
    )
    expect(buffer().doc).toEqual({
      doctype: 'CRM Organization',
      __newDocument: true,
    })
    m.unmount()
  })
})
