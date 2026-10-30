import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import LinkedDocsListView from '@/components/ListViews/LinkedDocsListView.vue'

const columns = [
  { label: 'Document', key: 'title', width: '19rem' },
  { label: 'Master', key: 'reference_doctype', width: '12rem' },
]

function openLinked(doctype, name) {
  const open = vi.spyOn(window, 'open').mockImplementation(() => null)
  const w = mount(LinkedDocsListView, {
    props: {
      rows: [
        {
          title: name,
          reference_doctype: doctype,
          reference_docname: name,
        },
      ],
      columns,
      linkedDocsResource: {},
      unlinkLinkedDoc: () => {},
    },
  })
  w.el
    .querySelector('.lucide-external-link')
    .dispatchEvent(new MouseEvent('click', { bubbles: true }))
  return open.mock.calls.at(-1)?.[0]
}

afterEach(() => vi.restoreAllMocks())

describe('LinkedDocsListView open icon', () => {
  it('opens a linked deal on its deal page', () => {
    expect(openLinked('CRM Deal', 'CRM-DEAL-2026-00042')).toBe(
      '/crm/deals/CRM-DEAL-2026-00042',
    )
  })

  it('encodes a name that carries URL syntax', () => {
    const name = 'Smith & Sons #2/Durban'
    expect(openLinked('CRM Organization', name)).toBe(
      `/crm/organizations/${encodeURIComponent(name)}`,
    )
    expect(openLinked('CRM Task', '7?x=1')).toBe(
      `/crm/tasks/view?open=${encodeURIComponent('7?x=1')}`,
    )
  })

  it('opens a doctype the CRM has no page for in the desk', () => {
    expect(openLinked('CRM Enrichment Run', 'ENR-0001')).toBe(
      '/app/crm-enrichment-run/ENR-0001',
    )
    expect(openLinked('CRM Notification', 'abc123')).toBe(
      '/app/crm-notification/abc123',
    )
  })
})
