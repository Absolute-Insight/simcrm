import { describe, it, expect } from 'vitest'
import { fakeBackend } from './fakeBackend.js'
import { flushPromises } from './flush.js'
import { mount } from './mount.js'
import { Badge, Button } from 'frappe-ui'
import EmailAccountList from '@/components/Settings/EmailAccountList.vue'

const ACCOUNTS = Array.from({ length: 12 }, (_, i) => ({
  name: `Rep ${i + 1}`,
  email_account_name: `Rep ${i + 1}`,
  email_id: `rep${i + 1}@mbp.co.za`,
  service: 'GMail',
  enable_incoming: 1,
  enable_outgoing: 1,
  default_incoming: 0,
  default_outgoing: 0,
}))

describe('EmailAccountList', () => {
  it('reaches accounts past the first page (FE-123)', async () => {
    const backend = fakeBackend()
    backend.handlers['frappe.client.get_list'] = ({ limit_start, limit }) =>
      ACCOUNTS.slice(limit_start, limit_start + limit).map((a) => ({ ...a }))
    const w = mount(EmailAccountList, { stubs: { Badge, Button } })
    await flushPromises()

    const shown = () =>
      ACCOUNTS.filter((a) => w.el.textContent.includes(a.email_id)).length
    expect(shown()).toBeLessThan(ACCOUNTS.length)

    const more = [...w.el.querySelectorAll('button')].find(
      (b) => b.textContent.trim() === 'Load More',
    )
    expect(more).toBeTruthy()
    more.click()
    await flushPromises()
    expect(shown()).toBe(ACCOUNTS.length)
    expect(w.el.textContent).not.toContain('Load More')
  })
})
