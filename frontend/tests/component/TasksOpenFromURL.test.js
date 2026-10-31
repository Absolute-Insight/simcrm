import { nextTick, reactive } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// The real Tasks page, its children stubbed. ViewControls hands the page the
// list resource through v-model, and the rows land later, as on a first visit
// with nothing cached.

const { state } = vi.hoisted(() => ({
  state: { modals: [], setList: null, listRows: null },
}))
for (const path of [
  '@/components/ViewBreadcrumbs.vue',
  '@/components/CustomActions.vue',
  '@/components/LayoutHeader.vue',
  '@/components/ListViews/EmptyState.vue',
  '@/components/ui/ErrorState.vue',
  '@/components/ui/SkeletonTable.vue',
  '@/components/Kanban/KanbanView.vue',
]) {
  vi.doMock(path, () => ({ default: { render: () => null } }))
}
vi.mock('@/components/ViewControls.vue', () => ({
  default: {
    emits: ['update:modelValue'],
    setup(_, { emit }) {
      state.setList = (list) => emit('update:modelValue', list)
      return () => null
    },
  },
}))
vi.mock('@/components/ListViews/TasksListView.vue', () => ({
  default: {
    props: ['rows'],
    render() {
      state.listRows = this.rows
      return null
    },
  },
}))
vi.mock('@/composables/doctypeModal', () => ({
  useDoctypeModal: () => ({ showModal: (modal) => state.modals.push(modal) }),
}))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({}) }))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: () => ({}) }),
}))
vi.mock('@/utils', () => ({ formatDate: (d) => d, ConfirmDelete: () => [] }))
vi.mock('@/composables/useTimelinePreferences', () => ({
  timestampCell: (v) => v,
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { viewType: 'list' }, query: {} }),
  useRouter: () => ({ push() {} }),
}))

const { default: Tasks } = await import('@/pages/Tasks.vue')

afterEach(() => window.history.replaceState(null, '', '/'))

const flush = async () => {
  for (let i = 0; i < 3; i++) {
    await new Promise((resolve) => setTimeout(resolve))
    await nextTick()
  }
}

describe('a link to /crm/tasks/view?open=<task>', () => {
  it('opens that task once the list has loaded', async () => {
    window.history.replaceState(null, '', '/crm/tasks/view?open=42')
    state.modals = []
    mount(Tasks, {
      plugins: [
        (app) => {
          app.config.globalProperties.$route = { params: { viewType: 'list' } }
        },
      ],
    })
    await flush()
    const list = reactive({ data: null, error: null, params: {} })
    state.setList(list)
    await flush()
    list.data = {
      view_type: 'list',
      row_count: 1,
      total_count: 1,
      rows: ['name', 'title'],
      columns: [{ key: 'title', label: 'Title', type: 'Data' }],
      data: [{ name: 42, title: 'Send quote to Sasol' }],
    }
    await flush()

    expect(state.listRows.map((row) => row.name)).toEqual([42])
    expect(state.modals.map((modal) => modal.name)).toEqual([42])
    expect(window.location.search).toBe('')
  })
})
