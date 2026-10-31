import { describe, it, expect, vi, afterEach } from 'vitest'
import { reactive } from 'vue'
import { fakeBackend } from './fakeBackend.js'
import { flushPromises } from './flush.js'
import { mount } from './mount.js'
import { setValue } from './stubs.js'

vi.mock('frappe-ui', async (importOriginal) => {
  const { FormControl } = await import('./stubs.js')
  return { ...(await importOriginal()), FormControl }
})
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    users: reactive({ data: { crmUsers: [{ name: 'mgr@mbp.example' }] } }),
    isAdmin: () => false,
  }),
}))

import { Button, ErrorMessage } from 'frappe-ui'
import InviteUserPage from '@/components/Settings/InviteUserPage.vue'

const intersection = Set.prototype.intersection
afterEach(() => {
  Set.prototype.intersection = intersection
})

describe('InviteUserPage (FE-134)', () => {
  it('works on a browser without Set.prototype.intersection', async () => {
    // Safari 16 / iPadOS 16: ES2025's Set methods, which nothing polyfills
    delete Set.prototype.intersection
    const backend = fakeBackend()
    backend.handlers['frappe.client.get_list'] = () => [
      { name: 'INV-1', email: 'old@mbp.example', role: 'Sales User' },
    ]
    const errors = []
    const w = mount(InviteUserPage, {
      stubs: { Button, ErrorMessage },
      plugins: [
        { install: (app) => (app.config.errorHandler = (e) => errors.push(e)) },
      ],
    })
    await flushPromises()

    const box = () => w.el.querySelector('textarea')
    setValue(box(), 'mgr@mbp.example, new@mbp.example')
    await flushPromises()
    expect(errors).toEqual([])
    expect(w.el.textContent).toContain(
      'User with email mgr@mbp.example already exists',
    )

    setValue(box(), 'old@mbp.example')
    await flushPromises()
    expect(errors).toEqual([])
    expect(w.el.textContent).toContain(
      'User with email old@mbp.example already invited',
    )
  })
})
