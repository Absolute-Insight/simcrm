/* eslint-disable vue/one-component-per-file -- stand-ins for frappe-ui */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent, h, reactive } from 'vue'
import { fakeBackend } from './fakeBackend.js'
import { flushPromises } from './flush.js'
import { mount } from './mount.js'
import { buttonByText } from './stubs.js'

const { toast, docs } = vi.hoisted(() => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
  docs: {},
}))
vi.mock('frappe-ui', async (importOriginal) => {
  const { FormControl } = await import('./stubs.js')
  // a row's menu as plain buttons; the real one opens a reka-ui popover
  const Dropdown = defineComponent({
    props: { options: { type: Array, default: () => [] } },
    setup: (props) => () =>
      h(
        'div',
        props.options.map((o) =>
          h('button', { onClick: () => o.onClick?.() }, o.label),
        ),
      ),
  })
  // the Details panel only; the tab strip is reka-ui's
  const Tabs = defineComponent({
    props: { tabs: { type: Array, default: () => [] } },
    setup:
      (props, { slots }) =>
      () =>
        h('div', slots['tab-panel']?.({ tab: props.tabs[0] })),
  })
  return { ...(await importOriginal()), Dropdown, FormControl, Tabs, toast }
})
// A document resource for a saved source, the new-document draft (no save)
// for an empty name -- the shapes useDocument hands back.
vi.mock('@/data/document', () => ({
  useDocument: (doctype, name) => {
    if (!name) {
      return { document: reactive({ doc: {}, fieldPropertyOverrides: {} }) }
    }
    return {
      document: reactive({
        doc: docs[name],
        reload() {},
        syncLeads: { loading: false, error: null, submit() {} },
      }),
    }
  },
}))
vi.mock('@/stores/meta', () => ({
  getMeta: () => ({ meta: reactive({ data: null }), getFields: () => [] }),
}))
vi.mock('@/components/Controls/Link.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/Controls/Grid.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/Settings/LeadSyncing/FailureLogs.vue', () => ({
  default: { render: () => null },
}))

import { Button, ErrorMessage } from 'frappe-ui'
import LeadSyncSourcePage from '@/components/Settings/LeadSyncing/LeadSyncSourcePage.vue'

const SOURCE = {
  name: 'Website FB',
  type: 'Facebook',
  enabled: 1,
  access_token: '*****',
  facebook_page: null,
  facebook_lead_form: null,
  background_sync_frequency: 'Hourly',
  last_synced_at: null,
}

let backend
beforeEach(() => {
  docs[SOURCE.name] = { ...SOURCE }
  backend = fakeBackend()
  backend.handlers['frappe.client.get_list'] = () => [
    {
      name: SOURCE.name,
      enabled: 1,
      type: 'Facebook',
      last_synced_at: null,
      facebook_lead_form: null,
    },
  ]
  backend.handlers['frappe.client.set_value'] = ({ name, fieldname }) => ({
    ...docs[name],
    ...fieldname,
  })
  for (const fn of Object.values(toast)) fn.mockReset()
})

async function mountPage() {
  const w = mount(LeadSyncSourcePage, { stubs: { Button, ErrorMessage } })
  await flushPromises()
  return w
}

const buttons = (w) =>
  [...w.el.querySelectorAll('button')].map((b) => b.textContent.trim())

describe('Lead sync sources', () => {
  it('Duplicate opens a new source of the same type, not the original (FE-135)', async () => {
    const w = await mountPage()
    buttonByText(w.el, 'Duplicate').click()
    await flushPromises()

    expect(buttons(w)).toContain('Create')
    expect(buttons(w)).not.toContain('Update')
    expect(buttons(w)).not.toContain('Sync Now')
    expect(w.el.querySelector('[data-label="Source Name"]').value).toBe('')
    expect(w.el.querySelector('[data-label="Source Type"]').value).toBe(
      'Facebook',
    )
  })
})
