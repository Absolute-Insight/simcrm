import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import { flush, modalStubs, translation } from './stubs.js'
import ContactModal from '@/components/Modals/ContactModal.vue'
import CreateDocumentModal from '@/components/Modals/CreateDocumentModal.vue'
import { useDocument } from '@/data/document'

// The create buffer `useDocument(doctype)` hands out is shared for the whole
// session and must keep its `doctype` key: a Form Script's getField() reads it
// and returns null without. Lead, Deal, Organization and Doctype modals reset
// it through resetNewDocument(); these two wrote `{}` instead.
const S = vi.hoisted(() => ({ inserted: [] }))

vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  call: vi.fn(async (method, params) => {
    S.inserted.push(params.doc)
    return { name: 'NEW-1' }
  }),
  toast: { error() {}, success() {}, info() {}, warning() {} },
  createResource: (opts) => ({
    data: null,
    fetch() {},
    reload() {},
    submit(params) {
      S.inserted.push(params.doc)
      opts.onSuccess?.({ name: 'NEW-1' })
    },
    ...opts,
  }),
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
vi.mock('@/stores/meta', async () => {
  const { ref } = await import('vue')
  return {
    getMeta: () => ({ doctypeMeta: ref({ title_field: 'title' }) }),
  }
})
vi.mock('@/composables/useAttachments', () => ({
  useAttachments: () => ({ trackOldFile() {}, processPendingDeletions() {} }),
}))
vi.mock('@/composables/doctypeModal', () => ({
  useDoctypeModal: () => ({ showModal() {} }),
}))

const open = (component, props) =>
  mount(component, {
    props: { modelValue: true, ...props },
    stubs: modalStubs,
    plugins: [translation],
  })

describe('ContactModal create buffer', () => {
  it('opens on a fresh draft that names its doctype', async () => {
    const buffer = useDocument('Contact').document
    buffer.doc = { first_name: 'Left over', company_name: 'Old Co' }
    open(ContactModal, { contact: { first_name: 'Ann' } })
    await flush()
    expect(buffer.doc.doctype).toBe('Contact')
    expect(buffer.doc.__newDocument).toBe(true)
    expect(buffer.doc.first_name).toBe('Ann')
    expect(buffer.doc.company_name).toBeUndefined()
  })

  it('is a fresh draft again after a create', async () => {
    const buffer = useDocument('Contact').document
    const w = open(ContactModal, { contact: { first_name: 'Ann' } })
    await flush()
    await w.vm.$.setupState.createContact()
    await flush()
    expect(S.inserted.at(-1)).toMatchObject({
      doctype: 'Contact',
      first_name: 'Ann',
    })
    expect(buffer.doc).toEqual({ __newDocument: true, doctype: 'Contact' })
  })
})

describe('CreateDocumentModal create buffer', () => {
  it('does not reopen with an abandoned form, and names its doctype', async () => {
    const buffer = useDocument('CRM Industry').document
    buffer.doc = { title: 'Abandoned', notes: 'typed, then closed' }
    open(CreateDocumentModal, { doctype: 'CRM Industry', data: 'Mining' })
    await flush()
    expect(buffer.doc).toEqual({
      __newDocument: true,
      doctype: 'CRM Industry',
      title: 'Mining',
    })
  })

  it('is a fresh draft again after a create', async () => {
    const buffer = useDocument('CRM Industry').document
    const w = open(CreateDocumentModal, {
      doctype: 'CRM Industry',
      data: 'Mining',
    })
    await flush()
    await w.vm.$.setupState.create()
    expect(S.inserted.at(-1)).toMatchObject({
      doctype: 'CRM Industry',
      title: 'Mining',
    })
    expect(buffer.doc).toEqual({ __newDocument: true, doctype: 'CRM Industry' })
  })
})
