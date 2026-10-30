import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import AllModals from '@/components/Activities/AllModals.vue'

const S = vi.hoisted(() => ({ toasts: [], refuse: null }))

vi.mock('frappe-ui', () => ({
  call: () => Promise.reject(S.refuse),
  toast: { error: (m) => S.toasts.push(m) },
}))
vi.mock('@/components/Modals/EventModal.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/composables/doctypeModal', () => ({
  useDoctypeModal: () => ({ showModal: () => {} }),
}))
vi.mock('@/utils/taskClosing', () => ({ collectClosingValues: () => ({}) }))
vi.mock('vue-router', async (importOriginal) => ({
  ...(await importOriginal()),
  useRoute: () => ({}),
  useRouter: () => ({ push: () => {} }),
}))

describe('AllModals.deleteTask', () => {
  beforeEach(() => {
    S.toasts.length = 0
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('says why a refused task delete did not happen', async () => {
    // TaskArea closes its confirm dialog first and does not await this.
    S.refuse = Object.assign(new Error('Not permitted'), {
      exc_type: 'PermissionError',
      status: 403,
      _server_messages: JSON.stringify([
        JSON.stringify({ message: 'Not permitted to delete this task' }),
      ]),
    })
    const reload = vi.fn()
    const w = mount(AllModals, {
      props: { doctype: 'CRM Deal', modelValue: { reload } },
    })

    await expect(w.vm.deleteTask('TASK-0001')).resolves.toBeUndefined()

    expect(S.toasts).toEqual(['Not permitted to delete this task'])
    expect(reload).not.toHaveBeenCalled()
  })
})
