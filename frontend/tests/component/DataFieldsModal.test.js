import { describe, expect, it, vi } from 'vitest'
import { setConfig } from 'frappe-ui'
import { mount } from './mount.js'
import { flush, modalStubs, translation } from './stubs.js'
import DataFieldsModal from '@/components/Modals/DataFieldsModal.vue'

// frappe-ui's real createResource loads the layout; the save is refused.
const S = vi.hoisted(() => ({ saves: 0, reported: [] }))

vi.mock('frappe-ui', async (importOriginal) => {
  const { Dialog } = await import('./stubs.js')
  return {
    ...(await importOriginal()),
    Dialog,
    // save_fields_layout refused (a PermissionError, a dropped connection)
    call: () => {
      S.saves++
      return Promise.reject(
        Object.assign(new Error('Not permitted'), {
          exc_type: 'PermissionError',
        }),
      )
    },
  }
})
vi.mock('@/components/ui/ToneBadge.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/FieldLayout/FieldLayout.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/FieldLayoutEditor.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/utils/reportActionError', () => ({
  reportActionError: (e, message) => S.reported.push(message),
}))

setConfig('resourceFetcher', () =>
  Promise.resolve([
    {
      name: 'first_tab',
      sections: [
        { name: 's', columns: [{ name: 'c', fields: [{ fieldname: 'x' }] }] },
      ],
    },
  ]),
)

describe('DataFieldsModal', () => {
  it('lets the user retry Save after a failed save', async () => {
    const w = mount(DataFieldsModal, {
      props: { modelValue: true, doctype: 'CRM Deal' },
      stubs: modalStubs,
      plugins: [translation],
    })
    await new Promise((r) => setTimeout(r, 150)) // onMounted's debounced reload
    await flush()
    const save = () => w.el.querySelector('button[data-label="Save"]')

    save().click()
    await flush()
    expect(S.reported).toEqual(['Could not save the layout.'])
    expect(save().dataset.loading).toBe('false')

    save().click()
    await flush()
    expect(S.saves).toBe(2)
    w.unmount()
  })
})
