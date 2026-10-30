import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { mount } from './mount.js'
import { flush, modalStubs, translation } from './stubs.js'
import ListBulkActions from '@/components/ListBulkActions.vue'
import AssignmentModal from '@/components/Modals/AssignmentModal.vue'

// The real ListBulkActions with the real AssignmentModal it opens.
const S = vi.hoisted(() => ({ calls: [], link: null }))

vi.mock('frappe-ui', async (importOriginal) => {
  const { h } = await import('vue')
  return {
    ...(await importOriginal()),
    call: (method, args) => {
      S.calls.push({ method, args })
      return Promise.resolve({})
    },
    toast: { success() {}, error() {}, create() {} },
    Tooltip: {
      name: 'Tooltip',
      render() {
        return h('span', this.$slots.default?.())
      },
    },
  }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push() {} }) }))
vi.mock('@/utils', () => ({ setupListCustomizations: async () => ({}) }))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog() {}, $socket: null }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    users: { data: { crmUsers: [] } },
    getUser: (name) => ({ full_name: name, user_image: null }),
  }),
}))
vi.mock('@/components/Modals/EditValueModal.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/UserAvatar.vue', () => ({
  default: { render: () => null },
}))
// The real Link emits `change` with the picked user's name.
vi.mock('@/components/Controls/Link.vue', () => ({
  default: {
    name: 'Link',
    emits: ['change'],
    setup(_, { emit, slots }) {
      S.link = emit
      return () => h('div', slots.trigger?.())
    },
  },
}))

const errors = []

async function listPage() {
  const w = mount(ListBulkActions, {
    props: { modelValue: { data: null, reload() {} }, doctype: 'CRM Lead' },
    stubs: {
      ...modalStubs,
      DeleteLinkedDocModal: { render: () => null },
      BulkDeleteLinkedDocModal: { render: () => null },
    },
    plugins: [
      translation,
      (app) => (app.config.errorHandler = (e) => errors.push(e)),
    ],
  })
  await flush()
  return {
    ...w,
    async assignTo(names) {
      const actions = w.vm.bulkActions(new Set(names), () => {})
      actions.find((a) => a.label === 'Assign To').onClick()
      await flush()
    },
    async pick(user) {
      S.link('change', user)
      await flush()
    },
    chips: () =>
      [...w.el.querySelectorAll('.ml-1')].map((n) => n.textContent.trim()),
    async removeChip(user) {
      const chip = [...w.el.querySelectorAll('.ml-1')].find(
        (n) => n.textContent.trim() === user,
      )
      chip.nextElementSibling.click() // its x button
      await flush()
    },
    async update() {
      w.el.querySelector('button[data-label="Update"]').click()
      await flush()
    },
  }
}

const addMultiple = () =>
  S.calls
    .filter((c) => c.method === 'frappe.desk.form.assign_to.add_multiple')
    .map((c) => [c.args.name, c.args.assign_to])

beforeEach(() => {
  S.calls.length = 0
  errors.length = 0
})

describe('bulk Assign To, twice in one list visit', () => {
  it('opens empty and assigns the same rep to the second batch', async () => {
    const page = await listPage()
    await page.assignTo(['LEAD-1'])
    await page.pick('rep.a@example.com')
    await page.update()

    await page.assignTo(['LEAD-2'])
    expect(page.chips()).toEqual([])
    await page.pick('rep.a@example.com')
    await page.update()

    expect(addMultiple()).toEqual([
      ['["LEAD-1"]', ['rep.a@example.com']],
      ['["LEAD-2"]', ['rep.a@example.com']],
    ])
    page.unmount()
  })

  it('assigns every chip shown at Update, and never removes in bulk', async () => {
    const page = await listPage()
    await page.assignTo(['LEAD-1'])
    await page.pick('rep.a@example.com')
    await page.update()

    await page.assignTo(['LEAD-2'])
    await page.pick('rep.a@example.com')
    await page.pick('rep.b@example.com')
    await page.removeChip('rep.a@example.com')
    expect(page.chips()).toEqual(['rep.b@example.com'])
    await page.update()

    // Removing is per record (it reads props.doc), so bulk mode must not try.
    expect(errors.map(String)).toEqual([])
    expect(S.calls.map((c) => c.method)).toEqual([
      'frappe.desk.form.assign_to.add_multiple',
      'frappe.desk.form.assign_to.add_multiple',
    ])
    expect(addMultiple()[1]).toEqual(['["LEAD-2"]', ['rep.b@example.com']])
    page.unmount()
  })

  it('AssignmentModal in bulk mode assigns a rep it opened with', async () => {
    const w = mount(AssignmentModal, {
      props: {
        modelValue: true,
        assignees: [{ name: 'rep.a@example.com' }],
        docs: new Set(['LEAD-9']),
        doctype: 'CRM Lead',
      },
      stubs: modalStubs,
      plugins: [translation],
    })
    await flush()
    w.el.querySelector('button[data-label="Update"]').click()
    await flush()
    expect(addMultiple()).toEqual([['["LEAD-9"]', ['rep.a@example.com']]])
    w.unmount()
  })
})
