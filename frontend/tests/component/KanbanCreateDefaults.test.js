import { defineComponent, h, nextTick } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// The real Deals and Leads pages on a status kanban, with their children
// stubbed: the board's "+" opens the new-record modal with that column's
// value, and the header's Create opens it with none.

const { state } = vi.hoisted(() => ({
  state: { kanban: null, modal: null, opened: [], broadcast: {} },
}))
const blank = (name) => ({
  default: { name, render: () => null },
})
for (const path of [
  '@/components/ViewBreadcrumbs.vue',
  '@/components/MultipleAvatar.vue',
  '@/components/CustomActions.vue',
  '@/components/ListViews/DealsListView.vue',
  '@/components/ListViews/LeadsListView.vue',
  '@/components/ListViews/EmptyState.vue',
  '@/components/ui/ErrorState.vue',
  '@/components/ui/SkeletonTable.vue',
  '@/components/Kanban/KanbanActivityCounts.vue',
]) {
  vi.doMock(path, () => blank(path))
}
vi.mock('@/components/LayoutHeader.vue', () => ({
  default: {
    render() {
      return h('div', this.$slots['right-header']?.())
    },
  },
}))
vi.mock('@/components/Kanban/KanbanView.vue', () => ({
  default: {
    props: ['options', 'modelValue'],
    render() {
      state.kanban = this
      return null
    },
  },
}))
const modal = {
  props: ['defaults', 'modelValue'],
  emits: ['update:modelValue'],
  mounted() {
    state.opened.push(JSON.parse(JSON.stringify(this.defaults)))
    state.modal = this
  },
  render: () => null,
}
vi.mock('@/components/Modals/DealModal.vue', () => ({ default: modal }))
vi.mock('@/components/Modals/LeadModal.vue', () => ({ default: modal }))
// What ViewControls hands the page through v-model: a board grouped by status.
vi.mock('@/components/ViewControls.vue', () => ({
  default: {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    mounted() {
      this.$emit('update:modelValue', {
        error: null,
        params: { column_field: 'status' },
        data: {
          view_type: 'kanban',
          rows: ['name', 'status'],
          fields: [],
          data: [
            { column: { name: 'New' }, data: [] },
            { column: { name: 'Won' }, data: [] },
          ],
        },
      })
    },
    render: () => null,
  },
}))
vi.mock('@/composables/doctypeModal', () => ({
  useDoctypeModal: () => ({ showModal() {} }),
}))
vi.mock('@/composables/useBroadcast', () => ({
  useBroadcast: () => ({ on: (event, fn) => (state.broadcast[event] = fn) }),
}))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({}) }))
vi.mock('@/stores/global', () => ({ globalStore: () => ({}) }))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: () => ({}) }),
}))
vi.mock('@/stores/organizations', () => ({
  organizationsStore: () => ({ getOrganization: () => ({}) }),
}))
vi.mock('@/stores/statuses', () => ({
  statusesStore: () => ({
    getDealStatus: () => ({}),
    getLeadStatus: () => ({}),
  }),
}))
vi.mock('@/composables/telephony', async () => ({
  callEnabled: (await import('vue')).ref(false),
}))
vi.mock('@/composables/useTimelinePreferences', () => ({
  timestampCell: (v) => v,
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { viewType: 'kanban' }, query: {} }),
}))

const pages = {
  Deals: (await import('@/pages/Deals.vue')).default,
  Leads: (await import('@/pages/Leads.vue')).default,
}

const Button = defineComponent({
  props: { label: { type: String, default: '' } },
  setup:
    (props, { attrs }) =>
    () =>
      h('button', { onClick: attrs.onClick }, props.label),
})

async function flush() {
  for (let i = 0; i < 4; i++) {
    await new Promise((resolve) => setTimeout(resolve))
    await nextTick()
  }
}

async function plusThenCreate(page) {
  state.opened = []
  const w = mount(pages[page], {
    stubs: { Button, Badge: { render: () => null } },
  })
  await flush()
  state.kanban.options.onNewClick({ column: { name: 'Won' } }) // "+" on Won
  await flush()
  state.modal.$emit('update:modelValue', false) // closed without saving
  await flush()
  ;[...w.el.querySelectorAll('button')]
    .find((b) => b.textContent === 'Create')
    .click() // then the header's Create
  await flush()
  return w
}

describe('the header Create starts a clean record', () => {
  for (const page of ['Deals', 'Leads']) {
    it(`on ${page}, after a kanban column's "+"`, async () => {
      await plusThenCreate(page)
      expect(state.opened).toEqual([{ status: 'Won' }, {}])
    })
  }

  it('on Leads, when another surface asks for a new lead', async () => {
    await plusThenCreate('Leads')
    state.modal.$emit('update:modelValue', false)
    await flush()
    state.broadcast.trigger_lead_create(true)
    await flush()
    expect(state.opened.at(-1)).toEqual({})
  })
})
