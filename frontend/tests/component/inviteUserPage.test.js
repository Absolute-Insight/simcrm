import { defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

vi.mock('frappe-ui', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
    createResource: (options) => ({ options, submit: vi.fn(), loading: false }),
    createListResource: () => ({
      data: [
        { name: 'INV-1', email: 'Pending.Rep@Example.com', role: 'Sales User' },
      ],
      reload: vi.fn(),
      delete: { submit: vi.fn(), loading: false, params: {} },
    }),
    // the textarea the page types into; @input falls through to it
    FormControl: defineComponent({
      props: { type: { type: String, default: 'text' } },
      setup: (props) => () =>
        props.type === 'textarea' ? h('textarea') : h('div'),
    }),
  }
})

vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    users: { data: { crmUsers: [{ name: 'sarah@mbp.co.za' }] } },
    isAdmin: () => true,
  }),
}))

const { default: InviteUserPage } = await import(
  '@/components/Settings/InviteUserPage.vue'
)

const stubs = {
  Button: defineComponent({
    props: { label: { type: String, default: '' }, disabled: Boolean },
    setup: (props) => () =>
      h('button', { disabled: props.disabled }, props.label),
  }),
  ErrorMessage: defineComponent({ setup: () => () => h('div') }),
}

async function typeInvitees(w, value) {
  const textarea = w.el.querySelector('textarea')
  textarea.value = value
  textarea.dispatchEvent(new Event('input'))
  await w.nextTick()
}

function sendButton(w) {
  return [...w.el.querySelectorAll('button')].find(
    (b) => b.textContent === 'Send Invites',
  )
}

// User.autoname lower-cases an address and the server now compares it that
// way; the page's own guard compared the typed capitals and let it through.
describe('InviteUserPage', () => {
  it('knows an existing member typed with different capitals', async () => {
    const w = mount(InviteUserPage, { stubs })
    await typeInvitees(w, 'Sarah@MBP.co.za')

    expect(w.el.textContent).toContain(
      'User with email sarah@mbp.co.za already exists',
    )
    expect(sendButton(w).disabled).toBe(true)
  })

  it('knows a pending invitation typed with different capitals', async () => {
    const w = mount(InviteUserPage, { stubs })
    await typeInvitees(w, 'pending.rep@EXAMPLE.com')

    expect(w.el.textContent).toContain(
      'User with email pending.rep@example.com already invited',
    )
    expect(sendButton(w).disabled).toBe(true)
  })
})
