import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

const frappe = vi.hoisted(() => ({
  call: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  linkedDocs: [],
}))

vi.mock('frappe-ui', () => ({
  call: frappe.call,
  toast: frappe.toast,
  createResource: () => ({ data: frappe.linkedDocs, reload: vi.fn() }),
}))

const passthrough = defineComponent({
  setup:
    (_, { slots }) =>
    () =>
      h('div', slots.default?.()),
})

vi.mock('reka-ui', () => ({
  DialogTitle: passthrough,
  DialogDescription: passthrough,
  VisuallyHidden: passthrough,
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/data/document', () => ({
  markDocumentAsDeleted: vi.fn(),
  unmarkDocumentAsDeleted: vi.fn(),
  expireDeletionMarker: vi.fn(),
}))

const { default: DeleteLinkedDocModal } = await import(
  '@/components/DeleteLinkedDocModal.vue'
)
const { default: BulkDeleteLinkedDocModal } = await import(
  '@/components/BulkDeleteLinkedDocModal.vue'
)

const stubs = {
  Dialog: passthrough,
  LinkedDocsListView: passthrough,
  Button: defineComponent({
    props: { label: { type: String, default: '' } },
    emits: ['click'],
    setup:
      (props, { emit, slots }) =>
      () =>
        h('button', { onClick: () => emit('click') }, [
          props.label,
          slots.default?.(),
        ]),
  }),
}

async function click(w, label) {
  const button = [...w.el.querySelectorAll('button')].find(
    (b) => b.textContent.trim() === label,
  )
  expect(button, `a button labelled "${label}"`).toBeTruthy()
  button.click()
  await w.nextTick()
  // let the awaited call() settle and the toast fire
  await new Promise((resolve) => setTimeout(resolve))
}

beforeEach(() => {
  frappe.call.mockReset()
  Object.values(frappe.toast).forEach((fn) => fn.mockReset())
})

let wrapper
afterEach(() => wrapper?.unmount())

describe('DeleteLinkedDocModal', () => {
  it('names the contact being deleted when it unlinks a deal', async () => {
    // A deal lists its contacts in a child table, and the deal is what comes
    // back as linked. Unlinking without saying which contact cleared them all.
    frappe.linkedDocs = [
      {
        reference_doctype: 'CRM Deal',
        reference_docname: 'CRM-DEAL-1',
        title: 'Deal 1',
      },
    ]
    frappe.call.mockResolvedValue({ unlinked: ['CRM-DEAL-1'], skipped: [] })
    wrapper = mount(DeleteLinkedDocModal, {
      props: {
        modelValue: true,
        name: 'Contacts',
        doctype: 'Contact',
        docname: 'contact-a',
      },
      stubs,
    })

    await click(wrapper, 'Unlink All')
    await click(wrapper, 'Unlink Linked Item')

    expect(frappe.call).toHaveBeenCalledWith(
      'crm.api.doc.remove_linked_doc_reference',
      expect.objectContaining({
        items: [{ doctype: 'CRM Deal', docname: 'CRM-DEAL-1' }],
        remove_contact: true,
        contact: 'contact-a',
      }),
    )
  })
})

describe('BulkDeleteLinkedDocModal', () => {
  const mountBulk = () =>
    mount(BulkDeleteLinkedDocModal, {
      props: {
        modelValue: true,
        doctype: 'CRM Organization',
        items: ['ORG-1', 'ORG-2'],
        reload: vi.fn(),
      },
      stubs,
    })

  it('says which records were not deleted, and why', async () => {
    frappe.call.mockResolvedValue({
      queued: false,
      count: 1,
      failed: [
        {
          docname: 'ORG-2',
          reason: 'Cannot delete ORG-2 because it is linked with RUN-1',
        },
      ],
    })
    wrapper = mountBulk()

    await click(wrapper, 'Unlink & Delete 2 items')
    await click(wrapper, 'Unlink & Delete')

    expect(frappe.toast.success).not.toHaveBeenCalled()
    expect(frappe.toast.error).toHaveBeenCalledWith(
      'Deleted 1 of 2. ORG-2 was not deleted: Cannot delete ORG-2 because it is linked with RUN-1',
    )
  })

  it('still reports a clean delete as done', async () => {
    frappe.call.mockResolvedValue({ queued: false, count: 2, failed: [] })
    wrapper = mountBulk()

    await click(wrapper, 'Unlink & Delete 2 items')
    await click(wrapper, 'Unlink & Delete')

    expect(frappe.toast.success).toHaveBeenCalledWith('Deleted 2')
    expect(frappe.toast.error).not.toHaveBeenCalled()
  })
})
