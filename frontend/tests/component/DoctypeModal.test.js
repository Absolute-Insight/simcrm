import { beforeEach, describe, expect, it, vi } from 'vitest'
import { setConfig } from 'frappe-ui'
import { mount } from './mount.js'
import { flush, modalStubs, translation } from './stubs.js'
import DoctypeModal from '@/components/Modals/DoctypeModal.vue'
import { useDocument } from '@/data/document'

// The real useDocument (so the session-wide create buffer is the real one) on
// frappe-ui's real createResource, with the fetcher recording inserts.
const S = vi.hoisted(() => ({ inserts: [], hold: false }))

vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  createDocumentResource: () => ({ doc: {}, save: { submit() {} } }),
  call: () => Promise.resolve(),
  toast: { error() {}, success() {}, info() {} },
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
vi.mock('@/components/FieldLayout/FieldLayout.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/CustomActions.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/data/script', () => ({
  getScript: () => ({ setupScript: async () => [], scripts: {} }),
}))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog() {}, $socket: null, makeCall() {} }),
}))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({}) }))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ isManager: () => false }),
}))
vi.mock('@/composables/useAttachments', () => ({
  useAttachments: () => ({ trackOldFile() {}, processPendingDeletions() {} }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push() {} }) }))

setConfig('resourceFetcher', (options) => {
  if (options.url === 'frappe.client.insert') {
    S.inserts.push(JSON.parse(JSON.stringify(options.params.doc)))
    if (S.hold) return new Promise(() => {}) // a slow server
    return Promise.resolve({ ...options.params.doc, name: 'NEW-1' })
  }
  return Promise.resolve([]) // layout, history
})

async function open(props) {
  const w = mount(DoctypeModal, {
    props: { modelValue: true, docname: null, ...props },
    stubs: modalStubs,
    plugins: [translation],
  })
  await flush()
  const createButton = () => w.el.querySelector('button[data-label="Create"]')
  return { ...w, createButton }
}

beforeEach(() => {
  S.inserts.length = 0
  S.hold = false
})

describe('DoctypeModal create mode', () => {
  it('does not inherit the reference of a create form that was closed unsaved', async () => {
    // Deal -> New Task carries the deal as defaults; the dialog is dismissed
    // (DoctypeModals v-ifs it on show, so closing unmounts it).
    const first = await open({
      doctype: 'CRM Task',
      defaults: { reference_doctype: 'CRM Deal', reference_docname: 'DEAL-A' },
    })
    first.unmount()

    // Tasks page -> Create Task: no reference.
    const second = await open({
      doctype: 'CRM Task',
      defaults: { status: 'Backlog', priority: 'Low' },
    })
    second.createButton().click()
    await flush()

    expect(S.inserts).toHaveLength(1)
    expect(S.inserts[0]).toMatchObject({
      doctype: 'CRM Task',
      status: 'Backlog',
    })
    expect(S.inserts[0].reference_doctype).toBeUndefined()
    expect(S.inserts[0].reference_docname).toBeUndefined()
    second.unmount()
  })

  it('leaves a fresh draft, not {}, after a successful create', async () => {
    const m = await open({
      doctype: 'CRM Task',
      defaults: { reference_doctype: 'CRM Deal', reference_docname: 'DEAL-B' },
    })
    m.createButton().click()
    await flush()
    expect(S.inserts).toHaveLength(1)
    // The shared buffer must stay a draft of the doctype (a Form Script's
    // getField needs `doctype`), with nothing of the saved record left in it.
    expect(useDocument('CRM Task').document.doc).toEqual({
      doctype: 'CRM Task',
      __newDocument: true,
    })
    m.unmount()
  })

  it('shows Create busy while the insert is in flight and ignores a second click', async () => {
    S.hold = true
    const m = await open({ doctype: 'FCRM Note', defaults: {} })
    m.createButton().click()
    await flush()
    expect(m.createButton().dataset.loading).toBe('true')
    m.createButton().click()
    await flush()
    expect(S.inserts).toHaveLength(1)
    m.unmount()
  })

  it('sends one insert for a double click that lands before the re-render', async () => {
    S.hold = true
    const m = await open({ doctype: 'FCRM Note', defaults: {} })
    m.createButton().click()
    m.createButton().click()
    await flush()
    expect(S.inserts).toHaveLength(1)
    m.unmount()
  })
})
