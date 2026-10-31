import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { mount } from './mount.js'
import { flush, modalStubs, translation } from './stubs.js'
import DeleteLinkedDocModal from '@/components/DeleteLinkedDocModal.vue'

const S = vi.hoisted(() => ({
  call: null,
  toast: null,
  push: null,
  unmark: null,
}))

vi.mock('frappe-ui', async (importOriginal) => {
  S.call = vi.fn()
  S.toast = { error: vi.fn(), success: vi.fn() }
  return {
    ...(await importOriginal()),
    createResource: () => reactive({ data: [], reload() {} }),
    call: S.call,
    toast: S.toast,
  }
})
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
vi.mock('vue-router', () => {
  S.push = vi.fn()
  return { useRouter: () => ({ push: S.push }) }
})
vi.mock('@/data/document', () => {
  S.unmark = vi.fn()
  return {
    markDocumentAsDeleted() {},
    unmarkDocumentAsDeleted: S.unmark,
    expireDeletionMarker() {},
  }
})

function linkExists() {
  const e = new Error('LinkExistsError')
  e.exc_type = 'LinkExistsError'
  e.messages = [
    'Cannot delete or cancel because CRM Deal DEAL-42 is linked with CRM Task TASK-7',
  ]
  return e
}

const errors = []

function open() {
  const w = mount(DeleteLinkedDocModal, {
    props: {
      modelValue: true,
      name: 'Deals',
      doctype: 'CRM Deal',
      docname: 'DEAL-42',
    },
    stubs: modalStubs,
    plugins: [
      translation,
      (app) => (app.config.errorHandler = (e) => errors.push(e)),
    ],
  })
  const deleteButton = () => w.el.querySelector('button[data-label="Delete"]')
  return { ...w, deleteButton }
}

beforeEach(() => {
  S.call.mockReset()
  S.toast.error.mockReset()
  S.push.mockReset()
  S.unmark.mockReset()
  errors.length = 0
})

describe('DeleteLinkedDocModal delete', () => {
  it('tells the user when the server refuses the delete', async () => {
    S.call.mockRejectedValue(linkExists())
    const m = open()
    await flush()
    m.deleteButton().click()
    await flush()

    expect(S.toast.error).toHaveBeenCalledWith(
      'Cannot delete or cancel because CRM Deal DEAL-42 is linked with CRM Task TASK-7',
    )
    expect(S.unmark).toHaveBeenCalledWith('CRM Deal', 'DEAL-42')
    expect(S.push).not.toHaveBeenCalled()
    expect(errors).toEqual([])
    // Not left busy: the user can try again once the link is removed.
    expect(m.deleteButton().dataset.loading).toBe('false')
    m.unmount()
  })

  it('shows Delete busy and sends one request for a double click', async () => {
    let resolve
    S.call.mockImplementation(() => new Promise((r) => (resolve = r)))
    const m = open()
    await flush()
    m.deleteButton().click()
    m.deleteButton().click()
    await flush()
    expect(m.deleteButton().dataset.loading).toBe('true')
    expect(S.call).toHaveBeenCalledTimes(1)
    resolve({})
    await flush()
    expect(S.push).toHaveBeenCalledWith({ name: 'Deals' })
    m.unmount()
  })
})
