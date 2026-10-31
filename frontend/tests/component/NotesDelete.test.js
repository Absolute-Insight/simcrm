import { defineComponent, h, nextTick, reactive } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// The real Notes page with one note, its card menu captured from the
// Dropdown, and the confirm dialog captured from $dialog.

const { state } = vi.hoisted(() => ({
  state: { menu: null, dialogs: [], toasts: [], call: null },
}))

vi.mock('frappe-ui', () => ({
  call: (...args) => state.call(...args),
  toast: { error: (message) => state.toasts.push(message), success() {} },
  Tooltip: {
    render() {
      return this.$slots.default?.()
    },
  },
  Dropdown: {
    props: ['options'],
    render() {
      state.menu = this.options
      return null
    },
  },
}))
vi.mock('frappe-ui/experimental', () => ({
  TextEditor: { render: () => null },
  ListFooter: { render: () => null },
}))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog: (dialog) => state.dialogs.push(dialog) }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: () => ({ full_name: 'Rep One' }) }),
}))
vi.mock('@/utils', () => ({ timeAgo: () => '1 day ago', formatDate: (d) => d }))
vi.mock('@/composables/doctypeModal', () => ({
  useDoctypeModal: () => ({ showModal() {} }),
}))
const notes = reactive({
  data: {
    data: [
      {
        name: 'NOTE-0001',
        title: 'Site visit',
        content: '',
        owner: 'rep@example.com',
        modified: '2026-10-20 09:00:00',
      },
    ],
    page_length_count: 20,
    row_count: 1,
    total_count: 1,
  },
  error: null,
  reload: vi.fn(),
})
vi.mock('@/components/ViewControls.vue', () => ({
  default: {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    setup(_, { emit }) {
      emit('update:modelValue', notes)
      return () => null
    },
  },
}))
for (const path of [
  '@/components/ViewBreadcrumbs.vue',
  '@/components/LayoutHeader.vue',
  '@/components/UserAvatar.vue',
  '@/components/ListViews/EmptyState.vue',
  '@/components/ui/ErrorState.vue',
  '@/components/ui/Skeleton.vue',
]) {
  vi.doMock(path, () => ({ default: { render: () => null } }))
}

const { default: Notes } = await import('@/pages/Notes.vue')

const Button = defineComponent({ render: () => h('button') })

async function openMenuAndDelete(answer) {
  state.dialogs = []
  state.toasts = []
  state.call = vi.fn(answer)
  notes.reload.mockClear()
  mount(Notes, { stubs: { Button } })
  await nextTick()
  state.menu.find((o) => o.label === 'Delete').onClick()
  await nextTick()
}

const settle = () => new Promise((resolve) => setTimeout(resolve))

describe('deleting a note from its card', () => {
  it('asks first, and deletes only once confirmed', async () => {
    await openMenuAndDelete(() => Promise.resolve())
    expect(state.call).not.toHaveBeenCalled()
    expect(state.dialogs).toHaveLength(1)

    const close = vi.fn()
    state.dialogs[0].actions
      .find((a) => a.label === 'Delete')
      .onClick({ close })
    await settle()
    expect(state.call).toHaveBeenCalledWith('frappe.client.delete', {
      doctype: 'FCRM Note',
      name: 'NOTE-0001',
    })
    expect(notes.reload).toHaveBeenCalled()
    expect(close).toHaveBeenCalled()
  })

  it('says so when the server refuses', async () => {
    await openMenuAndDelete(() =>
      Promise.reject(
        Object.assign(new Error('PermissionError'), {
          exc_type: 'PermissionError',
          status: 403,
        }),
      ),
    )
    const close = vi.fn()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    state.dialogs[0].actions
      .find((a) => a.label === 'Delete')
      .onClick({ close })
    await settle()
    expect(state.toasts).toHaveLength(1)
    expect(notes.reload).not.toHaveBeenCalled()
  })
})
