import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises } from './flush.js'
import { mount } from './mount.js'

const { call, toast } = vi.hoisted(() => ({
  call: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))
vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  call,
  toast,
}))

import { Button, ErrorMessage, FormControl } from 'frappe-ui'
import EmailEdit from '@/components/Settings/EmailEdit.vue'

const stubs = { Button, ErrorMessage, FormControl }

// As create_email_account stores a Custom account on 587 with IMAP over SSL.
const CUSTOM = {
  name: 'Vectora',
  email_account_name: 'Vectora',
  email_id: 'crm@vectora.example.org',
  service: '',
  password: '**********',
  email_server: 'imap.ionos.de',
  use_ssl: 1,
  use_starttls: 0,
  smtp_server: 'smtp.ionos.de',
  smtp_port: '587',
  use_tls: 1,
  use_ssl_for_outgoing: 0,
  enable_incoming: true,
  enable_outgoing: true,
  default_incoming: false,
  default_outgoing: true,
  create_lead_from_incoming_email: false,
}

function field(el, name) {
  return el.querySelector(`[name="${name}"]`)
}
function type(input, value) {
  input.value = value
  input.dispatchEvent(new Event('input'))
  input.dispatchEvent(new Event('change'))
}
function untick(input) {
  input.checked = false
  input.dispatchEvent(new Event('change'))
}
function button(el, label) {
  return [...el.querySelectorAll('button')].find(
    (b) => b.textContent.trim() === label,
  )
}
function sent(method) {
  return call.mock.calls.filter(([m]) => m === method).map(([, args]) => args)
}

beforeEach(() => {
  call.mockReset()
  for (const fn of Object.values(toast)) fn.mockReset()
})

describe('EmailEdit', () => {
  it('applies the Custom form port rules on edit (FE-52)', async () => {
    call.mockImplementation(async (_m, args) => ({ name: args.name }))
    const w = mount(EmailEdit, { props: { accountData: { ...CUSTOM } }, stubs })
    await flushPromises()
    type(field(w.el, 'smtp_port'), '465')
    untick(field(w.el, 'use_ssl'))
    await flushPromises()
    button(w.el, 'Update Account').click()
    await flushPromises()

    const [update] = sent('frappe.client.set_value')
    expect(update.fieldname).toMatchObject({
      smtp_port: '465',
      use_ssl_for_outgoing: 1,
      use_tls: 0,
      use_ssl: 0,
      use_starttls: 1,
      incoming_port: '143',
    })
  })

  it('reports success only once the field update has been saved too (FE-118)', async () => {
    call.mockImplementation(async (method, args) => {
      if (method === 'frappe.client.rename_doc') return args.new_name
      const e = new Error('/api/method/frappe.client.set_value ValidationError')
      e.messages = ['Invalid Outgoing Mail Server or Port']
      throw e
    })
    const w = mount(EmailEdit, {
      props: { accountData: { ...CUSTOM, service: 'GMail' } },
      stubs,
    })
    await flushPromises()
    type(field(w.el, 'email_account_name'), 'Vectora ZA')
    type(field(w.el, 'password'), 'new-password')
    await flushPromises()
    button(w.el, 'Update Account').click()
    await flushPromises()

    expect(sent('frappe.client.set_value')).toHaveLength(1)
    expect(toast.success).not.toHaveBeenCalled()
    expect(w.emitted['update:step']).toBeUndefined()
    expect(w.el.textContent).toContain('Failed to update email account')

    // The rename went through: a retry saves the fields under the new name
    // instead of renaming an account that no longer exists.
    call.mockImplementation(async (_m, args) => ({ name: args.name }))
    button(w.el, 'Update Account').click()
    await flushPromises()
    expect(sent('frappe.client.rename_doc')).toHaveLength(1)
    expect(sent('frappe.client.set_value')[1].name).toBe('Vectora ZA')
    expect(toast.success).toHaveBeenCalledOnce()
    expect(w.emitted['update:step']).toEqual([['email-list']])
  })
})
