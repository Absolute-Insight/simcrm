import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { setConfig } from 'frappe-ui'
import { mount } from './mount.js'
import { flush, modalStubs, translation } from './stubs.js'
import CreateDocumentModal from '@/components/Modals/CreateDocumentModal.vue'
import ContactModal from '@/components/Modals/ContactModal.vue'

// The generic Link quick-create (CreateDocumentModal) and the specialised
// ContactModal both load Contact's Quick Entry layout through frappe-ui's real
// createResource. FieldLayout records the tabs each one renders.
const S = vi.hoisted(() => ({ tabs: null }))

vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  createDocumentResource: () => ({ doc: {}, save: { submit() {} } }),
  call: () => Promise.resolve(),
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
vi.mock('@/components/FieldLayout/FieldLayout.vue', () => ({
  default: {
    props: ['tabs'],
    render() {
      S.tabs = this.tabs
      return null
    },
  },
}))
vi.mock('@/data/script', () => ({
  getScript: () => ({ setupScript: async () => [], scripts: {} }),
}))
vi.mock('@/stores/global', () => ({ globalStore: () => ({}) }))
vi.mock('@/stores/meta', () => ({
  getMeta: () => ({
    doctypeMeta: ref({ autoname: 'naming_series:', title_field: 'full_name' }),
  }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ isManager: () => false }),
}))
vi.mock('@/composables/useAttachments', () => ({
  useAttachments: () => ({ trackOldFile() {}, processPendingDeletions() {} }),
}))
vi.mock('@/composables/doctypeModal', () => ({
  useDoctypeModal: () => ({ showModal() {} }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push() {} }) }))

// Contact's meta makes email_id and mobile_no read-only: they are derived from
// the email_ids / phone_nos child tables. ContactModal opens them up.
setConfig('resourceFetcher', () =>
  Promise.resolve([
    {
      name: 'first_tab',
      sections: [
        {
          name: 's',
          columns: [
            {
              name: 'c',
              fields: [
                { fieldname: 'first_name', fieldtype: 'Data', reqd: 0 },
                { fieldname: 'email_id', fieldtype: 'Data', read_only: 1 },
                { fieldname: 'mobile_no', fieldtype: 'Data', read_only: 1 },
              ],
            },
          ],
        },
      ],
    },
  ]),
)

async function open(component, props) {
  const w = mount(component, {
    props: { modelValue: true, ...props },
    stubs: modalStubs,
    plugins: [translation],
  })
  await flush(8)
  const fields = Object.fromEntries(
    S.tabs[0].sections[0].columns[0].fields.map((f) => [f.fieldname, f]),
  )
  w.unmount()
  return fields
}

// One sequence in one test: frappe-ui's resource cache lives for the module,
// so it is a page session, and the order of the opens is the point.
describe('Quick Entry layouts', () => {
  it('New Contact and a Link quick-create of a Contact each get their own', async () => {
    // Deal -> Choose Existing Contact -> type a new name -> Create new.
    const quickCreate = { doctype: 'Contact', data: { first_name: 'Jane' } }
    await open(CreateDocumentModal, quickCreate)

    // Later, Contacts -> New Contact: its email and mobile are editable.
    const contact = await open(ContactModal, { contact: {} })
    expect(contact.email_id.read_only).toBe(false)
    expect(contact.mobile_no.read_only).toBe(false)
    expect(contact.first_name.reqd).toBe(1)

    // ...and the quick-create still shows the layout as configured.
    const again = await open(CreateDocumentModal, quickCreate)
    expect(again.email_id.read_only).toBe(1)
    expect(again.first_name.reqd).toBe(0)
  })
})
