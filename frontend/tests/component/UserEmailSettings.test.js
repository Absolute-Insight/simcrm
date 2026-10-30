import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent, h } from 'vue'
import { fakeBackend, frappeError } from './fakeBackend.js'
import { collectRejections, flushPromises } from './flush.js'
import { mount } from './mount.js'

const { toast } = vi.hoisted(() => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))
vi.mock('frappe-ui', async (importOriginal) => {
  // the picker's options as buttons that select themselves
  const Combobox = defineComponent({
    props: { options: { type: Array, default: () => [] } },
    emits: ['update:selected-option'],
    setup:
      (props, { emit }) =>
      () =>
        h(
          'ul',
          { 'data-label': 'picker' },
          props.options.map((option) =>
            h('li', [
              h(
                'button',
                { onClick: () => emit('update:selected-option', option) },
                option.label,
              ),
            ]),
          ),
        ),
  })
  return { ...(await importOriginal()), Combobox, toast }
})
vi.mock('frappe-ui/experimental', async () => {
  const { TextEditor } = await import('./stubs.js')
  return { TextEditor }
})

import { Button, ErrorMessage } from 'frappe-ui'
import SettingsLayoutBase from '@/components/Layouts/SettingsLayoutBase.vue'
import UserEmailSettings from '@/components/Settings/Profile/UserEmailSettings.vue'

// the app resolves SettingsLayoutBase through unplugin-vue-components
const stubs = { Button, ErrorMessage, SettingsLayoutBase }

const PROFILE = {
  name: 'rep@mbp.example',
  email: 'rep@mbp.example',
  email_signature: '',
  user_emails: [],
}

let backend
beforeEach(() => {
  backend = fakeBackend()
  backend.handlers['crm.api.user.get_profile'] = () => ({ ...PROFILE })
  backend.handlers['crm.api.user.get_linkable_email_accounts'] = () => [
    { name: 'Sales Desk', email_id: 'sales@mbp.example' },
  ]
  // what a Sales User gets from frappe.client.get_list on Email Account
  backend.handlers['frappe.client.get_list'] = ({ doctype }) => {
    if (doctype === 'Email Account') {
      const e = frappeError('No permission for Email Account', 'get_list')
      e.exc_type = 'PermissionError'
      throw e
    }
    return []
  }
  toast.error.mockReset()
})

const picker = (w) =>
  [...w.el.querySelectorAll('[data-label="picker"] button')].map((b) =>
    b.textContent.trim(),
  )

describe('UserEmailSettings Add Email (FE-136)', () => {
  it('offers the accounts the rep may link', async () => {
    const w = mount(UserEmailSettings, { stubs })
    await flushPromises()
    expect(picker(w)).toEqual(['Sales Desk'])
  })

  it('says so when the accounts cannot be loaded', async () => {
    const failure = new TypeError('Failed to fetch')
    backend.handlers['crm.api.user.get_linkable_email_accounts'] = () => {
      throw failure
    }
    let w
    const rejections = await collectRejections(() => {
      w = mount(UserEmailSettings, { stubs })
    })
    expect(w.el.textContent).toContain(
      'Could not load the email accounts you can add.',
    )
    expect(rejections.filter((r) => r !== failure)).toEqual([])
  })
})
