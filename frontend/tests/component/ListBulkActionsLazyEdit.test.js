import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import { flush, modalStubs, translation } from './stubs.js'

// Bulk Edit loads its dialog on first use. S.edit decides what the fetch of
// that chunk does on each attempt.
const S = vi.hoisted(() => ({ edit: null, opened: 0, toast: [] }))

vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  call: async () => ({}),
  toast: {
    success() {},
    error: (message) => S.toast.push(message),
    create() {},
  },
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push() {} }) }))
vi.mock('@/utils', () => ({ setupListCustomizations: async () => ({}) }))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog() {}, $socket: null }),
}))
vi.mock('@/components/Modals/AssignmentModal.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/utils/lazyComponent', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    // the real helper, with the chunk fetch in the test's hands
    lazyComponent: (loader, options) =>
      actual.lazyComponent(() => S.edit(), options),
  }
})

const { default: ListBulkActions } = await import(
  '@/components/ListBulkActions.vue'
)
const Dialog = {
  mounted: () => S.opened++,
  render: () => null,
}

async function listPage() {
  const w = mount(ListBulkActions, {
    props: { modelValue: { data: null, reload() {} }, doctype: 'CRM Lead' },
    stubs: {
      ...modalStubs,
      DeleteLinkedDocModal: { render: () => null },
      BulkDeleteLinkedDocModal: { render: () => null },
    },
    plugins: [translation],
  })
  await flush()
  const edit = async () => {
    w.vm
      .bulkActions(new Set(['LEAD-1', 'LEAD-2']), () => {})
      .find((a) => a.label === 'Edit')
      .onClick()
    await flush()
  }
  return { ...w, edit }
}

beforeEach(() => {
  S.opened = 0
  S.toast.length = 0
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

describe('bulk Edit when its dialog cannot be fetched', () => {
  it('says so, and opens on the next click once the connection is back', async () => {
    S.edit = () =>
      Promise.reject(new Error('Failed to fetch dynamically imported module'))
    const page = await listPage()
    await page.edit()
    expect(S.opened).toBe(0)
    expect(S.toast).toEqual([
      'Could not load the bulk edit dialog. Check your connection and try again.',
    ])
    expect(page.vm.$.setupState.showEditModal).toBe(false)
    // nothing was thrown away with it
    expect([...page.vm.$.setupState.selectedValues]).toEqual([
      'LEAD-1',
      'LEAD-2',
    ])

    S.edit = async () => ({ default: Dialog })
    await page.edit()
    expect(S.opened).toBe(1)
    expect(S.toast).toHaveLength(1)
  })
})
