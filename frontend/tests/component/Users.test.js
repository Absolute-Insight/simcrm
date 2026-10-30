import { describe, it, expect, vi, beforeEach } from 'vitest'
import { reactive } from 'vue'
import { flushPromises } from './flush.js'
import { mount } from './mount.js'

vi.mock('frappe-ui', async (importOriginal) => {
  const { Select, TextInput } = await import('./stubs.js')
  return { ...(await importOriginal()), Select, TextInput }
})
vi.mock('@/components/Modals/AddExistingUserModal.vue', () => ({
  default: { render: () => null },
}))

const session = vi.hoisted(() => ({ manager: true }))
beforeEach(() => {
  session.manager = true
})

const ROLES = ['System Manager', 'Sales Manager', 'Sales User']
const crmUsers = [
  { name: 'Administrator', full_name: 'Administrator', role: 'System Manager' },
  {
    name: 'tnkosi@mbp.example',
    full_name: 'Thandi Nkosi',
    role: 'Sales Manager',
  },
  ...Array.from({ length: 10 }, (_, i) => ({
    name: `rep${i}@mbp.example`,
    full_name: `Rep ${i}`,
    role: ROLES[i % 3],
  })),
]
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    users: reactive({ data: { crmUsers }, loading: false }),
    isAdmin: () => true,
    isManager: () => session.manager,
  }),
}))

import { Button } from 'frappe-ui'
import Users from '@/components/Settings/Users.vue'

const rows = (w) => [...w.el.querySelectorAll('li')].map((li) => li.textContent)

describe('Settings › Users', () => {
  it('gives every role button its icon (FE-148)', async () => {
    // not a manager session: every row's role, Admin included, is a dropdown
    session.manager = false
    const w = mount(Users, { stubs: { Button } })
    await flushPromises()
    const iconOf = (label) =>
      [...w.el.querySelectorAll('li button')]
        .find((b) => b.textContent.trim() === label)
        ?.querySelector('[class*="lucide-"]')?.className
    expect(iconOf('Admin')).toContain('lucide-shield')
    expect(iconOf('Manager')).toContain('lucide-briefcase')
    expect(iconOf('Sales User')).toContain('lucide-user-check')
  })
})
