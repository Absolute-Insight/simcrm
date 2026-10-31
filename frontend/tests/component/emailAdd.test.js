import { defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

const frappe = vi.hoisted(() => ({ resources: [] }))

vi.mock('frappe-ui', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  createResource(options) {
    const resource = { options, submit: vi.fn(), loading: false }
    frappe.resources.push(resource)
    return resource
  },
}))

const { default: EmailAdd } = await import('@/components/Settings/EmailAdd.vue')

const stubs = {
  FormControl: defineComponent({ setup: () => () => h('div') }),
  Button: defineComponent({ setup: () => () => h('button') }),
  ErrorMessage: defineComponent({
    props: { message: { type: String, default: '' } },
    setup: (props) => () => h('p', { class: 'error' }, props.message),
  }),
}

describe('EmailAdd', () => {
  it("shows the server's reason an account was refused", async () => {
    const w = mount(EmailAdd, { stubs })
    const sendgrid = [...w.el.querySelectorAll('p')].find(
      (p) => p.textContent.trim() === 'Sendgrid',
    )
    sendgrid.parentElement.click()
    await w.nextTick()

    const create = frappe.resources.find(
      (r) => r.options.url === 'crm.api.settings.create_email_account',
    )
    // Sendgrid only sends mail; the server says so when incoming is ticked,
    // and "invalid credentials" sent the admin after an API key that was fine
    create.options.onError({
      messages: [
        'Sendgrid only sends email. Turn off Enable Incoming to add it.',
      ],
    })
    await w.nextTick()

    expect(w.el.querySelector('.error').textContent).toBe(
      'Sendgrid only sends email. Turn off Enable Incoming to add it.',
    )
  })

  it('falls back to a generic message when the server gave none', async () => {
    const w = mount(EmailAdd, { stubs })
    const gmail = [...w.el.querySelectorAll('p')].find(
      (p) => p.textContent.trim() === 'GMail',
    )
    gmail.parentElement.click()
    await w.nextTick()

    frappe.resources.at(-1).options.onError(new Error('network'))
    await w.nextTick()

    expect(w.el.querySelector('.error').textContent).toBe(
      'Failed to create email account: invalid credentials',
    )
  })
})
