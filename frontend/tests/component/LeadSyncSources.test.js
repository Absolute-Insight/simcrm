/* eslint-disable vue/one-component-per-file -- stand-ins for frappe-ui */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent, h, reactive } from 'vue'
import { fakeBackend } from './fakeBackend.js'
import { collectRejections, flushPromises } from './flush.js'
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

  it('Update on a source with no Lead Form reports success (FE-131)', async () => {
    const w = await mountPage()
    w.el.querySelector('li').click() // open the source for editing
    await flushPromises()
    expect(buttons(w)).toContain('Update')

    const rejections = await collectRejections(() =>
      buttonByText(w.el, 'Update').click(),
    )
    expect(backend.log.map((r) => r.url)).toContain('frappe.client.set_value')
    expect(toast.success).toHaveBeenCalledWith(
      'Lead sync source updated successfully',
    )
    expect(toast.error).not.toHaveBeenCalled()
    expect(rejections).toEqual([])
  })

  it('reverts a toggle that failed without server messages', async () => {
    const offline = new TypeError('Failed to fetch')
    backend.handlers['frappe.client.set_value'] = () => {
      throw offline
    }
    const w = await mountPage()
    const toggle = w.el.querySelector('li [role="switch"]')
    const rejections = await collectRejections(() => toggle.click())
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    expect(toast.error).toHaveBeenCalledWith('Failed to update source')
    expect(rejections.filter((r) => r !== offline)).toEqual([])
  })
})
