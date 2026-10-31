import { h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import NoteArea from '@/components/Activities/NoteArea.vue'

const S = vi.hoisted(() => ({ calls: [], dialogs: [], settle: null }))

// The menu is rendered as one button per option, so a test can pick Delete
// the way a rep does.
vi.mock('frappe-ui', async () => {
  const { h } = await import('vue')
  return {
    Dropdown: {
      props: ['options'],
      render() {
        return h(
          'div',
          (this.options || []).map((o) =>
            h('button', { 'data-option': o.label, onClick: o.onClick }),
          ),
        )
      },
    },
    call: (method, args) => {
      S.calls.push({ method, args })
      return new Promise((resolve) => (S.settle = resolve))
    },
    // Like sonner: the toast's id comes back, not the promise.
    toast: { promise: () => 'toast-id' },
  }
})
vi.mock('frappe-ui/experimental', () => ({
  TextEditor: { render: () => null },
}))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog: (d) => S.dialogs.push(d) }),
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ getUser: (u) => ({ full_name: u }) }),
}))
vi.mock('@/components/UserAvatar.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/Activities/TimelineTimestamp.vue', () => ({
  default: { render: () => null },
}))

const Button = { render: () => h('button') }

const note = {
  name: 'NOTE-0007',
  title: 'Site visit findings',
  content: '<p>Pump bay needs a new seal</p>',
  owner: 'rep@example.com',
  modified: '2026-10-29 10:00:00',
}

function deletes() {
  return S.calls.filter((c) => c.method === 'frappe.client.delete')
}

describe('NoteArea delete', () => {
  beforeEach(() => {
    S.calls.length = 0
    S.dialogs.length = 0
  })

  it('asks before deleting, and deletes only once the rep confirms', async () => {
    const reload = vi.fn()
    const w = mount(NoteArea, {
      props: { note, modalRef: {}, modelValue: { reload } },
      stubs: { Button },
    })
    w.el.querySelector('[data-option="Delete"]').click()

    expect(deletes()).toEqual([])
    expect(S.dialogs).toHaveLength(1)

    const confirm = S.dialogs[0].actions.find((a) => a.label === 'Delete')
    const close = vi.fn()
    confirm.onClick({ close })
    expect(close).toHaveBeenCalledOnce()
    expect(deletes()).toEqual([
      {
        method: 'frappe.client.delete',
        args: { doctype: 'FCRM Note', name: 'NOTE-0007' },
      },
    ])

    // The list reloads once the delete has landed, not alongside it.
    await new Promise((r) => setTimeout(r))
    expect(reload).not.toHaveBeenCalled()
    S.settle({})
    await new Promise((r) => setTimeout(r))
    expect(reload).toHaveBeenCalledOnce()
  })
})
