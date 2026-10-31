import { describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { mount } from './mount.js'

// The record the panel is showing; each test sets it before mounting.
const record = reactive({ doc: {} })

vi.mock('@/data/document', () => ({
  useDocument: () => ({
    document: record,
    triggerOnChange: vi.fn(),
    triggerButton: vi.fn(),
  }),
}))
vi.mock('@/stores/statuses', () => {
  const types = {
    'CRM Deal': { Qualification: 'Open', Won: 'Won', Lost: 'Lost' },
    'CRM Lead': { New: 'Open', Junk: 'Lost', Unqualified: 'Lost' },
  }
  const lookup = (doctype) => (name) =>
    types[doctype][name] ? { name, type: types[doctype][name] } : undefined
  return {
    statusesStore: () => ({
      getDealStatus: lookup('CRM Deal'),
      getLeadStatus: lookup('CRM Lead'),
    }),
  }
})
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    users: { data: { crmUsers: [] } },
    isManager: () => false,
    getUser: () => ({}),
  }),
}))
vi.mock('@/stores/meta', () => ({
  getMeta: () => ({
    getFormattedPercent: (v) => v,
    getFormattedFloat: (v) => v,
    getFormattedCurrency: (v) => v,
  }),
}))
vi.mock('@/composables/document', () => ({ createDocument: vi.fn() }))
vi.mock('@/components/Modals/SidePanelModal.vue', () => ({
  default: { render: () => null },
}))

const { default: SidePanelLayout } = await import(
  '@/components/SidePanelLayout.vue'
)

// The shared layout as the patch leaves it: the Lost Reason section is always
// there, and the page decides per record whether to show it.
function sections() {
  return [
    {
      name: 'lost_reason_section',
      label: 'Lost Reason',
      opened: true,
      columns: [
        {
          name: 'lost_reason_column',
          fields: [
            {
              fieldname: 'lost_reason',
              label: 'Lost Reason',
              fieldtype: 'Data',
            },
            { fieldname: 'lost_notes', label: 'Lost Notes', fieldtype: 'Text' },
          ],
        },
      ],
    },
    {
      name: 'details_section',
      label: 'Details',
      opened: true,
      columns: [
        {
          name: 'details_column',
          fields: [
            { fieldname: 'territory', label: 'Territory', fieldtype: 'Data' },
          ],
        },
      ],
    },
  ]
}

function panel(doctype, doc) {
  record.doc = { name: 'REC-1', ...doc }
  return mount(SidePanelLayout, {
    props: { doctype, docname: 'REC-1', sections: sections() },
    stubs: { Button: { render: () => null } },
  })
}

const shows = (el, text) => el.textContent.includes(text)

describe('the side panel Lost Reason section', () => {
  // It used to be added to and removed from the one layout every record
  // shares, by whichever record last changed status anywhere on the site.
  it('shows on a lost deal', async () => {
    const w = panel('CRM Deal', { status: 'Lost', lost_reason: 'Pricing' })
    await w.nextTick()

    expect(shows(w.el, 'Lost Reason')).toBe(true)
    expect(shows(w.el, 'Lost Notes')).toBe(true)
    expect(shows(w.el, 'Territory')).toBe(true)
  })

  it('stays off an open deal and a won one', async () => {
    for (const status of ['Qualification', 'Won']) {
      const w = panel('CRM Deal', { status })
      await w.nextTick()

      expect(shows(w.el, 'Lost Reason')).toBe(false)
      expect(shows(w.el, 'Lost Notes')).toBe(false)
      expect(shows(w.el, 'Territory')).toBe(true)
      w.unmount()
    }
  })

  it('follows the lead in view as its status changes', async () => {
    const w = panel('CRM Lead', { status: 'New' })
    await w.nextTick()
    expect(shows(w.el, 'Lost Reason')).toBe(false)

    record.doc.status = 'Junk'
    await w.nextTick()
    expect(shows(w.el, 'Lost Reason')).toBe(true)

    record.doc.status = 'New'
    await w.nextTick()
    expect(shows(w.el, 'Lost Reason')).toBe(false)
  })

  it('leaves the same fields alone on other doctypes', async () => {
    const w = panel('CRM Organization', {})
    await w.nextTick()

    expect(shows(w.el, 'Lost Notes')).toBe(true)
  })
})
