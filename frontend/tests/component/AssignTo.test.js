import { describe, expect, it, vi } from 'vitest'
import { h, reactive } from 'vue'
import { mount } from './mount.js'
import { flush, translation } from './stubs.js'
import AssignToBody from '@/components/AssignToBody.vue'

const S = vi.hoisted(() => ({ link: null }))

vi.mock('frappe-ui', async (importOriginal) => {
  const { h } = await import('vue')
  const pass = (name) => ({
    name,
    render() {
      return h('div', this.$slots.default?.({ open: true }))
    },
  })
  return {
    ...(await importOriginal()),
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
