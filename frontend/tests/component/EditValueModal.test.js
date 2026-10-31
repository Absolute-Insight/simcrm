import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import { findComponents, flush, modalStubs, translation } from './stubs.js'
import EditValueModal from '@/components/Modals/EditValueModal.vue'

const S = vi.hoisted(() => ({ updates: [] }))

vi.mock('frappe-ui', async (importOriginal) => {
  const actual = await importOriginal()
  const { h } = await import('vue')
  return {
    ...actual,
    // The field picker: an <input> whose change emits the chosen field.
    Combobox: {
      name: 'Combobox',
      props: ['options'],
      emits: ['update:selected-option'],
      render() {
        return h('input', {
          class: 'pick-field',
          onChange: (e) =>
            this.$emit(
              'update:selected-option',
              this.options.find((o) => o.value === e.target.value),
            ),
        })
      },
    },
    createResource: () => ({
      data: [
        {
          fieldname: 'custom_key_account',
          fieldtype: 'Check',
          value: 'custom_key_account',
        },
        {
          fieldname: 'custom_deal_type',
          fieldtype: 'Select',
          options: 'New\nRenewal\nUpsell',
          value: 'custom_deal_type',
        },
      ],
      fetch() {},
    }),
    call: (method, args) => {
      S.updates.push(args)
      return Promise.resolve([])
    },
    toast: { info() {}, error() {}, success() {} },
  }
})
vi.mock('frappe-ui/experimental', () => ({
  TextEditor: { render: () => null },
}))
vi.mock('@/components/Controls/Link.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/stores/statuses', () => ({
  statusesStore: () => ({
    getLeadStatus: () => ({}),
    getDealStatus: () => ({}),
  }),
}))

// frappe-ui v1's Select reports a pick only through update:modelValue; the
// pick is delivered the way reka's SelectRoot delivers it.
async function bulkEdit(fieldname, choice) {
  const w = mount(EditValueModal, {
    props: {
      modelValue: true,
      doctype: 'CRM Deal',
      selectedValues: new Set(['DEAL-1', 'DEAL-2']),
    },
    stubs: modalStubs,
    plugins: [translation],
  })
  await flush()
  const picker = w.el.querySelector('input.pick-field')
  picker.value = fieldname
  picker.dispatchEvent(new Event('change'))
  await flush()
  const [root] = findComponents(w.vm.$.subTree, 'SelectRoot')
  root.vnode.props['onUpdate:modelValue'](choice)
  await flush()
  w.el.querySelector('button[data-label^="Update"]').click()
  await flush()
  w.unmount()
  return S.updates.at(-1).data
}

describe('EditValueModal (list Bulk Edit)', () => {
  it('sends 1 when a Check field is set to Yes', async () => {
    expect(await bulkEdit('custom_key_account', 'Yes')).toEqual({
      custom_key_account: 1,
    })
  })

  it('sends the option picked for a Select field', async () => {
    expect(await bulkEdit('custom_deal_type', 'Renewal')).toEqual({
      custom_deal_type: 'Renewal',
    })
  })
})
