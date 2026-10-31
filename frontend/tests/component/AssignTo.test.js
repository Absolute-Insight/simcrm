import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h, reactive } from 'vue'
import { mount } from './mount.js'
import { flush, translation } from './stubs.js'
import AssignTo from '@/components/AssignTo.vue'
import AssignToBody from '@/components/AssignToBody.vue'

const S = vi.hoisted(() => ({
  link: null,
  serverOwner: '',
  call: null,
  toast: null,
}))

vi.mock('frappe-ui', async (importOriginal) => {
  const { h } = await import('vue')
  const pass = (name) => ({
    name,
    render() {
      return h('div', this.$slots.default?.({ open: true }))
    },
  })
  // What the server's ToDo hooks left in the owner field, read back by AssignTo.
  S.call = vi.fn(async (method, args) =>
    method === 'frappe.client.get_value'
      ? { [args.fieldname]: S.serverOwner }
      : undefined,
  )
  S.toast = { info: vi.fn(), error: vi.fn() }
  return {
    ...(await importOriginal()),
    call: S.call,
    toast: S.toast,
    Tooltip: pass('Tooltip'),
    Switch: { name: 'Switch', render: () => null },
    Popover: {
      name: 'Popover',
      render() {
        return h('div', [
          this.$slots.trigger?.({}),
          this.$slots.default?.({ open: true }),
        ])
      },
    },
    createResource: () => ({ submit: vi.fn(() => Promise.resolve()) }),
  }
})
vi.mock('@/components/UserAvatar.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/MultipleAvatar.vue', () => ({
  default: { render: () => null },
}))
// The real Link's dropdown footer has a Clear button that emits change('').
vi.mock('@/components/Controls/Link.vue', async () => {
  const { h } = await import('vue')
  return {
    default: {
      name: 'Link',
      emits: ['change'],
      setup(_, { emit, slots }) {
        S.link = emit
        return () => h('div', slots.trigger?.({}))
      },
    },
  }
})
const users = {
  'me@example.com': { name: 'me@example.com', full_name: 'Thandi Rep' },
}
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    users: { data: { crmUsers: Object.values(users) } },
    // like the real getUser: a falsy name is the session user
    getUser: (email) =>
      users[email || 'me@example.com'] || { name: email, full_name: email },
  }),
}))

const deal = reactive({ doc: {}, originalDoc: {}, save: { submit: vi.fn() } })
vi.mock('@/data/document', () => ({ useDocument: () => ({ document: deal }) }))

const stubs = { Button: { render: () => null } }

describe('Assign To picker (AssignToBody)', () => {
  it('"Clear" in the user dropdown adds nobody and sends nothing', async () => {
    const onUpdate = vi.fn(() => Promise.resolve())
    const state = reactive({ open: true, assignees: [] })
    const w = mount(
      {
        render: () =>
          h(AssignToBody, {
            modelValue: state.assignees,
            'onUpdate:modelValue': (v) => (state.assignees = v),
            doctype: 'CRM Deal',
            docname: 'DEAL-42',
            open: state.open,
            onUpdate,
          }),
      },
      { stubs, plugins: [translation] },
    )
    await flush()
    S.link('change', '')
    await flush()
    expect(state.assignees).toEqual([])
    expect(w.el.textContent).not.toContain('Thandi Rep')

    state.open = false // the popover closes: AssignToBody sends the change
    await flush()
    expect(onUpdate).not.toHaveBeenCalled()
    w.unmount()
  })
})

describe('AssignTo owner bookkeeping', () => {
  beforeEach(() => {
    S.call.mockClear()
    S.toast.info.mockReset()
    deal.save.submit.mockReset()
  })

  function open(doc, assignees) {
    deal.doc = { name: 'DEAL-42', ...doc }
    deal.originalDoc = { ...deal.doc }
    return mount(AssignTo, {
      props: { modelValue: assignees, doctype: 'CRM Deal', docname: 'DEAL-42' },
      stubs,
      plugins: [translation],
    })
  }

  // AssignToBody calls this (its onUpdate) once the add/remove are chosen.
  async function update(w, added, removed) {
    const resource = () => ({ submit: vi.fn(() => Promise.resolve()) })
    await w.vm.$.setupState.saveAssignees(
      added,
      removed,
      resource(),
      resource(),
    )
    await flush()
  }

  const A = { name: 'a@example.com', label: 'A Rep' }
  const B = { name: 'b@example.com', label: 'B Rep' }
  const C = { name: 'c@example.com', label: 'C Rep' }

  it('shows the owner the server set when an unowned deal gets an assignee', async () => {
    S.serverOwner = C.name
    const w = open({ deal_owner: '' }, [B, C])
    await update(w, [C.name], [])
    // The server makes the latest assignee the owner -- C, not B.
    expect(deal.doc.deal_owner).toBe(C.name)
    // and it is not left as an unsaved edit on the document
    expect(deal.originalDoc.deal_owner).toBe(C.name)
    expect(deal.save.submit).not.toHaveBeenCalled()
    expect(S.toast.info).toHaveBeenCalledWith(
      'Since you added a new assignee, the deal owner has been set to C Rep.',
    )
    w.unmount()
  })

  it('shows the new owner when an assignee is added to an owned deal', async () => {
    S.serverOwner = C.name
    const w = open({ deal_owner: A.name }, [A, C])
    await update(w, [C.name], [])
    expect(deal.doc.deal_owner).toBe(C.name)
    expect(deal.originalDoc.deal_owner).toBe(C.name)
    expect(deal.save.submit).not.toHaveBeenCalled()
    w.unmount()
  })

  it('hands an owner removed without a replacement to the next assignee', async () => {
    S.serverOwner = '' // removing the owner's assignment clears the owner
    const w = open({ deal_owner: A.name }, [B])
    await update(w, [], [A.name])
    expect(deal.doc.deal_owner).toBe(B.name)
    expect(deal.save.submit).toHaveBeenCalledTimes(1)
    expect(S.toast.info).toHaveBeenCalledWith(
      expect.stringContaining('the next available assignee B Rep.'),
    )
    w.unmount()
  })

  it('keeps the server owner when the owner is swapped for a new assignee', async () => {
    S.serverOwner = C.name
    const w = open({ deal_owner: A.name }, [B, C])
    await update(w, [C.name], [A.name])
    expect(deal.doc.deal_owner).toBe(C.name)
    expect(deal.save.submit).not.toHaveBeenCalled()
    w.unmount()
  })
})
