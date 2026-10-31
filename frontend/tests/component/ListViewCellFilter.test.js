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
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {}, params: { viewType: 'list' } }),
  useRouter: () => ({ push: () => {} }),
}))

const { Badge, Button, FormControl } = await import('frappe-ui')
const { getCallLogDetail } = await import('@/utils/callLog')
const { website } = await import('@/utils')
const views = {}
for (const name of [
  'CallLogsListView',
  'ContactsListView',
  'DealsListView',
  'LeadsListView',
  'OrganizationsListView',
  'TasksListView',
]) {
  views[name] = (await import(`@/components/ListViews/${name}.vue`)).default
}

const RouterLink = defineComponent({
  props: { to: { type: [Object, String], default: null } },
  setup:
    (_, { slots }) =>
    () =>
      h('a', slots.default?.()),
})

// Clicks the cell of `column` in the list view's only row and returns the
// applyFilter payload it emitted. ViewControls looks the clicked row's record
// up by `row.name` to filter on what is stored, not on what the cell shows.
function clickCell(view, row, column) {
  const emitted = []
  const columns = [{ label: 'Name', key: 'name', type: 'Data' }, column]
  const w = mount(views[view], {
    props: {
      rows: [row],
      columns,
      options: { selectable: false, showTooltip: false },
      onApplyFilter: (data) => emitted.push(data),
    },
    stubs: { Badge, Button, FormControl, RouterLink },
  })
  const cell = w.el.querySelector('.v-list .grid.items-center').children[1]
  // the label, or the badge inside it, not the avatar beside it
  const label = cell.querySelector('.truncate.text-base')
  const target = label.querySelector('.rounded-full') || label
  target.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  expect(emitted, `${view} emitted no applyFilter`).toHaveLength(1)
  return emitted[0]
}

describe('a clicked cell tells ViewControls which row it is on', () => {
  it('a Call Logs status badge', () => {
    const log = { name: 'CL-1', type: 'Outgoing', status: 'Busy' }
    const column = { label: 'Status', key: 'status', type: 'Select' }
    const row = {
      name: log.name,
      status: getCallLogDetail('status', log, [column]),
    }
    const { item, row: clicked } = clickCell('CallLogsListView', row, column)
    expect(item.label).toBe('Declined') // what the cell shows
    expect(clicked.name).toBe('CL-1')
  })

  it('a Call Logs receiver', () => {
    const log = { name: 'CL-2', _receiver: { label: 'Rep One' } }
    const column = { label: 'Receiver', key: 'receiver', type: 'Link' }
    const row = {
      name: log.name,
      receiver: getCallLogDetail('receiver', log, [column]),
    }
    expect(clickCell('CallLogsListView', row, column).row.name).toBe('CL-2')
  })

  it('an organization website', () => {
    const row = {
      name: 'Acme Pumps',
      website: website('https://www.acme-pumps.co.za'),
    }
    const column = { label: 'Website', key: 'website', type: 'Data' }
    expect(clickCell('OrganizationsListView', row, column).row.name).toBe(
      'Acme Pumps',
    )
  })

  for (const view of [
    'ContactsListView',
    'DealsListView',
    'LeadsListView',
    'TasksListView',
  ]) {
    it(`a plain cell on ${view}`, () => {
      const row = { name: 'DOC-1', territory: 'Gauteng' }
      const column = { label: 'Territory', key: 'territory', type: 'Link' }
      expect(clickCell(view, row, column).row.name).toBe('DOC-1')
    })
  }
})
