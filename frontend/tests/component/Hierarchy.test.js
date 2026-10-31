import { describe, it, expect, vi, beforeEach } from 'vitest'
import { reactive } from 'vue'
import { fakeBackend } from './fakeBackend.js'
import { flushPromises } from './flush.js'
import { mount } from './mount.js'

// What crm.api.session.get_users gives the store: enabled CRM users only,
// each with their highest CRM role.
vi.mock('@/stores/users', () => {
  const crmUsers = [
    {
      name: 'mgr@mbp.example',
      full_name: 'Mandla Manager',
      enabled: 1,
      role: 'Sales Manager',
    },
    {
      name: 'dir@mbp.example',
      full_name: 'Dineo Director',
      enabled: 1,
      role: 'System Manager',
    },
    {
      name: 'rep@mbp.example',
      full_name: 'Refilwe Rep',
      enabled: 1,
      role: 'Sales User',
    },
  ]
  return {
    usersStore: () => ({
      users: reactive({ data: { crmUsers }, loading: false }),
      getUserRole: (email) =>
        crmUsers.find((u) => u.name === email)?.role || null,
      isAdmin: () => true,
    }),
  }
})
vi.mock('@/stores/global', () => ({ globalStore: () => ({ $dialog() {} }) }))
vi.mock('@/stores/help', () => ({ openHelpCenter() {} }))

import { Button } from 'frappe-ui'
import Hierarchy from '@/components/Settings/Hierarchy/Hierarchy.vue'

const NODES = [
  {
    name: 'H-MGR',
    user: 'mgr@mbp.example',
    full_name: 'Mandla Manager',
    reports_to: null,
    is_group: 1,
  },
  {
    name: 'H-LEFT',
    user: 'left@mbp.example',
    full_name: 'Sipho Left',
    reports_to: 'H-MGR',
    is_group: 0,
  },
  {
    name: 'H-DIR',
    user: 'dir@mbp.example',
    full_name: 'Dineo Director',
    reports_to: null,
    is_group: 1,
  },
  {
    name: 'H-REP',
    user: 'rep@mbp.example',
    full_name: 'Refilwe Rep',
    reports_to: 'H-DIR',
    is_group: 0,
  },
]

beforeEach(() => {
  const backend = fakeBackend()
  backend.handlers['frappe.client.get'] = () => ({
    name: 'FCRM Settings',
    enable_sales_hierarchy: 1,
  })
  backend.handlers['frappe.client.get_list'] = () =>
    NODES.map((n) => ({ ...n }))
  // Sipho was disabled after being placed in the tree
  backend.handlers[
    'crm.fcrm.doctype.crm_sales_hierarchy.crm_sales_hierarchy.get_node_users'
  ] = () => [
    { user: 'mgr@mbp.example', enabled: 1, role: 'Sales Manager' },
    { user: 'left@mbp.example', enabled: 0, role: 'Sales User' },
    { user: 'dir@mbp.example', enabled: 1, role: 'System Manager' },
    { user: 'rep@mbp.example', enabled: 1, role: 'Sales User' },
  ]
})

async function rows() {
  const w = mount(Hierarchy, { stubs: { Button } })
  await flushPromises()
  return [...w.el.querySelectorAll('.hierarchy-tree-row')].map((r) =>
    r.textContent.replace(/\s+/g, ' ').trim(),
  )
}

describe('Sales Hierarchy (FE-133)', () => {
  it('badges a rep who was disabled after being placed', async () => {
    const sipho = (await rows()).find((t) => t.includes('Sipho Left'))
    expect(sipho).toContain('disabled')
  })

  it('keeps a System Manager node, with their reports under them', async () => {
    const shown = await rows()
    expect(shown).toHaveLength(4)
    const director = shown.findIndex((t) => t.includes('Dineo Director'))
    expect(director).toBeGreaterThan(-1)
    expect(shown[director]).toContain('System Manager')
    // depth-first: the report follows the manager it reports to
    expect(shown[director + 1]).toContain('Refilwe Rep')
  })
})
