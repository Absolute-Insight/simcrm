import { defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

vi.mock('@/components/ListBulkActions.vue', () => ({
  default: defineComponent({ render: () => h('div') }),
}))
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: 'rep@example.com' }),
}))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({}) }))
vi.mock('@/composables/useTimelinePreferences', () => ({
  timestampCell: () => ({ label: '', timeAgo: '' }),
}))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {}, params: {} }) }))

// The app registers these globally (main.js); the call-log row is wrapped in
// `<component is="button">`, which resolves to the registered Button.
const { Badge, Button, FormControl } = await import('frappe-ui')
const { statusColorMap } = await import('@/utils/callLog')
const views = {
  CallLogsListView: (
    await import('@/components/ListViews/CallLogsListView.vue')
  ).default,
  DealsListView: (await import('@/components/ListViews/DealsListView.vue'))
    .default,
  LeadsListView: (await import('@/components/ListViews/LeadsListView.vue'))
    .default,
}

function badgeClass(view, column, cell, label) {
  const w = mount(views[view], {
    props: {
      rows: [{ name: 'ROW-1', [column.key]: cell }],
      columns: [{ label: 'Name', key: 'name' }, column],
      options: { selectable: false, showTooltip: false },
    },
    stubs: { Badge, Button, FormControl },
  })
  const badge = [...w.el.querySelectorAll('.rounded-full')].find(
    (el) => el.textContent.trim() === label,
  )
  expect(badge, `no badge reading "${label}"`).toBeTruthy()
  return badge.className
}

describe('a status or SLA badge coloured orange renders orange', () => {
  it('a declined call in Call Logs', () => {
    expect(statusColorMap.Busy).toBe('orange')
    const cls = badgeClass(
      'CallLogsListView',
      { label: 'Status', key: 'status', type: 'Select' },
      { label: 'Declined', color: statusColorMap.Busy },
      'Declined',
    )
    expect(cls).toContain('text-ink-orange-9')
    expect(cls).not.toContain('bg-surface-gray-2')
  })

  for (const view of ['DealsListView', 'LeadsListView']) {
    it(`an SLA response that is due, on ${view}`, () => {
      const cls = badgeClass(
        view,
        { label: 'SLA Status', key: 'sla_status', type: 'Data' },
        { label: '31 Oct 2026', value: 'in 2 hours', color: 'orange' },
        'in 2 hours',
      )
      expect(cls).toContain('text-ink-orange-9')
      expect(cls).not.toContain('bg-surface-gray-2')
    })
  }
})
