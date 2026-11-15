import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { fakeBackend } from '../fakeBackend.js'
import { collectRejections, flushPromises } from '../flush.js'
import { mount } from '../mount.js'
import { memoryStorage } from '../stubs.js'

// frappe-ui v1's list resource keeps its request state on `.list`. These
// panes read `.loading` and `.error` off the resource itself, where both are
// undefined: a load that failed, or had not come back yet, was answered with
// the pane's empty state. The real panes, on the real list resource.
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    users: reactive({ data: { crmUsers: [] }, loading: false }),
    getUserRole: () => null,
    isAdmin: () => true,
    isManager: () => true,
  }),
}))
vi.mock('@/stores/global', () => ({ globalStore: () => ({ $dialog() {} }) }))
vi.mock('@/stores/help', () => ({ openHelpCenter() {} }))
vi.stubGlobal('localStorage', memoryStorage())

import { Button, createListResource } from 'frappe-ui'
import AutomationRules from '@/components/Settings/AutomationRules.vue'
import EmailAccountList from '@/components/Settings/EmailAccountList.vue'
import EmailTemplates from '@/components/Settings/EmailTemplate/EmailTemplates.vue'
import LeadSyncSources from '@/components/Settings/LeadSyncing/LeadSyncSources.vue'
import Hierarchy from '@/components/Settings/Hierarchy/Hierarchy.vue'

const provided = (key, doctype) => () => {
  const resource = createListResource({
    type: 'list',
    doctype,
    fields: ['name'],
    auto: true,
    pageLength: 20,
  })
  return [{ install: (app) => app.provide(key, resource) }]
}

const PANES = [
  {
    name: 'AutomationRules',
    component: AutomationRules,
    doctype: 'CRM Automation Rule',
    failed: 'Could not load the automation rules',
    empty: 'No rules yet',
  },
  {
    name: 'EmailAccountList',
    component: EmailAccountList,
    doctype: 'Email Account',
    failed: 'Could not load email accounts',
    empty: 'Add one to get started.',
  },
  {
    name: 'EmailTemplates',
    component: EmailTemplates,
    doctype: 'Email Template',
    plugins: provided('templates', 'Email Template'),
    failed: 'Could not load the email templates',
    empty: 'Add one to get started.',
  },
  {
    name: 'LeadSyncSources',
    component: LeadSyncSources,
    doctype: 'Lead Sync Source',
    plugins: provided('sources', 'Lead Sync Source'),
    failed: 'Could not load the lead sources',
    empty: 'Add and manage your lead sources here.',
  },
  {
    name: 'Hierarchy',
    component: Hierarchy,
    doctype: 'CRM Sales Hierarchy',
    failed: 'Could not load the hierarchy',
    empty: 'No users in hierarchy',
  },
]

let backend
/** Everything answers, and `list` decides what this pane's own list gets. */
function serve(pane, list) {
  backend = fakeBackend()
  backend.handlers['frappe.client.get'] = () => ({
    name: 'FCRM Settings',
    enable_sales_hierarchy: 1,
  })
  backend.handlers[
    'crm.fcrm.doctype.crm_sales_hierarchy.crm_sales_hierarchy.get_node_users'
  ] = () => []
  backend.handlers['frappe.client.get_list'] = (params) =>
    params.doctype === pane.doctype ? list(params) : []
}

async function open(pane) {
  const w = mount(pane.component, {
    props: { step: 'list' },
    stubs: { Button },
    plugins: pane.plugins?.() ?? [],
  })
  await flushPromises()
  return w
}

beforeEach(() => vi.restoreAllMocks())

describe.each(PANES)('$name list states', (pane) => {
  it('says the list could not be loaded, and offers a retry that works', async () => {
    let refuse = true
    serve(pane, () => {
      if (refuse) throw new Error('Failed to fetch')
      return []
    })
    let w
    // the resource re-throws what it reported: that one is expected
    await collectRejections(async () => (w = await open(pane)))
    expect(w.el.textContent).toContain(pane.failed)
    expect(w.el.textContent).not.toContain(pane.empty)

    refuse = false
    ;[...w.el.querySelectorAll('button')]
      .find((b) => b.textContent.includes('Try again'))
      .click()
    await flushPromises()
    expect(w.el.textContent).not.toContain(pane.failed)
    expect(w.el.textContent).toContain(pane.empty)
  })

  it('shows that it is loading, not that there is nothing', async () => {
    let answer
    serve(pane, () => new Promise((resolve) => (answer = resolve)))
    const w = await open(pane)
    expect(w.el.textContent).not.toContain(pane.empty)
    expect(w.el.textContent).not.toContain(pane.failed)

    answer([])
    await flushPromises()
    expect(w.el.textContent).toContain(pane.empty)
  })
})
