import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from './mount.js'
import { normalizeMenuOptions } from '../../node_modules/frappe-ui/src/components/Menu/utils.ts'
import FormBuilderPanel from '@/components/Settings/Forms/FormBuilderPanel.vue'

// What the panel asks the server for, answered per test. A seeded Lead form as
// crm.api.form.get_form_config returns one, and the picker catalog it loads.
const backend = vi.hoisted(() => ({
  calls: [],
  dropdowns: [],
  saveReply: null,
}))

const LEAD_FORM = {
  name: 'contact-sales',
  title: 'Contact sales',
  route: 'contact-sales',
  document_type: 'CRM Lead',
  published: 0,
  submit_button_label: 'Submit',
  description: '',
  success_message: '',
  redirect_url: '',
  allowed_embedding_domains: '',
  fields: [
    {
      fieldname: 'section_break_seed1',
      label: 'Personal Details',
      fieldtype: 'Section Break',
    },
    {
      fieldname: 'first_name',
      label: 'First Name',
      fieldtype: 'Data',
      reqd: 1,
    },
    { fieldname: 'email', label: 'Email', fieldtype: 'Data', options: 'Email' },
    { fieldname: 'column_break_seed2', label: '', fieldtype: 'Column Break' },
    { fieldname: 'last_name', label: 'Last Name', fieldtype: 'Data' },
  ],
  hidden_fields: [
    {
      fieldname: 'status',
      label: 'Status',
      fieldtype: 'Link',
      options: 'CRM Lead Status',
      default: 'New',
    },
  ],
}
const LEAD_CATALOG = [
  { fieldname: 'first_name', label: 'First Name', fieldtype: 'Data', reqd: 1 },
  { fieldname: 'last_name', label: 'Last Name', fieldtype: 'Data', reqd: 0 },
  { fieldname: 'email', label: 'Email', fieldtype: 'Data', reqd: 0 },
]

const copy = (v) => JSON.parse(JSON.stringify(v))
function fetchResource(url) {
  if (url === 'crm.api.form.get_form_config') return copy(LEAD_FORM)
  if (url === 'crm.api.form.get_form_fields') return copy(LEAD_CATALOG)
  throw new Error('unexpected resource ' + url)
}

vi.mock('frappe-ui', async (importOriginal) => {
  const actual = await importOriginal()
  const { defineComponent, h, reactive } = await import('vue')
  return {
    ...actual,
    call: async (method, args) => {
      backend.calls.push([method, JSON.parse(JSON.stringify(args))])
      if (method === 'crm.api.form.save_form')
        return backend.saveReply
          ? backend.saveReply(args)
          : { name: args.name, route: args.form.route }
      if (method === 'crm.api.form.link_field_guest_access')
        return { guest_can_select: true }
      if (method === 'frappe.client.get_list') return []
      throw new Error('unexpected call ' + method)
    },
    toast: { success() {}, error() {}, info() {} },
    // async like the real one, so the load's onSuccess runs after setup()
    // has defined the resources it touches
    createResource: (opts) => {
      const r = reactive({
        data: null,
        async reload() {
          await Promise.resolve()
          r.data = fetchResource(opts.url)
          opts.onSuccess?.(r.data)
          return r.data
        },
      })
      if (opts.auto) r.reload()
      return r
    },
    // the real Dropdown renders its rows only once opened; record what it was
    // given so a test can normalise it the way the real one does
    Dropdown: defineComponent({
      props: { options: { type: Array, default: () => [] } },
      setup(props, { slots }) {
        return () => {
          backend.dropdowns.push(props.options)
          return h('div', slots.default?.())
        }
      },
    }),
  }
})
vi.mock('@/stores/global', () => ({ globalStore: () => ({ $dialog() {} }) }))

const flush = async (n = 8) => {
  for (let i = 0; i < n; i++) {
    await Promise.resolve()
    await nextTick()
  }
}

let view
beforeEach(async () => {
  backend.calls = []
  backend.dropdowns = []
  backend.saveReply = null
  view = mount(FormBuilderPanel, { props: { name: 'contact-sales' } })
  await flush()
})

describe('FormBuilderPanel tabs', () => {
  const tab = (label) =>
    [...view.el.querySelectorAll('[role="tab"]')].find((t) =>
      t.textContent.includes(label),
    )
  async function press(el) {
    // reka-ui's TabsTrigger activates on a primary-button mousedown
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }))
    await flush()
  }

  it('opens the Settings tab (control)', async () => {
    await press(tab('Settings'))
    expect(view.el.textContent).toContain('Form details')
  })

  it('opens the Share tab, the only home of the embed snippet and allowed domains', async () => {
    const share = tab('Share')
    expect(share, 'a labelled Share trigger is rendered').toBeTruthy()
    await press(share)
    expect(view.el.textContent).toContain('Allowed domains')
  })
})

describe('FormBuilderPanel section menu', () => {
  it('offers the column operations alongside Rename', () => {
    // the real Dropdown draws exactly what normalizeMenuOptions keeps
    const rows = normalizeMenuOptions(backend.dropdowns.at(-1)).flatMap((g) =>
      g.options.map((o) => o.label),
    )
    expect(rows).toContain('Rename')
    // the seeded section has two of the four columns allowed: both apply
    expect(rows).toContain('Add Column')
    expect(rows).toContain('Remove Last Column')
  })
})
