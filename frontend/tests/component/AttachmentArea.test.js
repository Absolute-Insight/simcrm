import { h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import AttachmentArea from '@/components/Activities/AttachmentArea.vue'

const S = vi.hoisted(() => ({ dialogs: [], toasts: [], refuse: null }))

vi.mock('frappe-ui', () => ({
  call: () => Promise.reject(S.refuse),
  toast: { error: (m) => S.toasts.push(m) },
}))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog: (d) => S.dialogs.push(d) }),
}))
vi.mock('@/utils', () => ({
  convertSize: (n) => String(n),
  isImage: () => false,
}))
vi.mock('@/components/Icon.vue', () => ({ default: { render: () => null } }))
vi.mock('@/components/Activities/TimelineTimestamp.vue', () => ({
  default: { render: () => null },
}))

const Button = {
  inheritAttrs: false,
  render() {
    return h('button', {
      'data-tooltip': this.$attrs.tooltip,
      onClick: this.$attrs.onClick,
    })
  },
}

const attachment = {
  name: 'FILE-01',
  file_name: 'site-photo.jpg',
  file_type: 'JPG',
  file_url: '/private/files/site-photo.jpg',
  file_size: 1024,
  is_private: 1,
  creation: '2026-10-29 10:00:00',
}

// frappe answers a rep who can read the deal but not change its files with a
// PermissionError and the server's own sentence.
function permissionError(message) {
  return Object.assign(new Error('Not permitted'), {
    exc_type: 'PermissionError',
    status: 403,
    _server_messages: JSON.stringify([JSON.stringify({ message })]),
  })
}

async function confirm(tooltip) {
  const w = mount(AttachmentArea, {
    props: { attachments: [attachment] },
    stubs: { Button },
  })
  w.el.querySelector(`[data-tooltip="${tooltip}"]`).click()
  const close = vi.fn()
  // The dialog awaits the action: it must settle, not reject unhandled.
  await S.dialogs[0].actions[0].onClick({ close })
  return { close, emitted: w.emitted }
}

describe('AttachmentArea refused actions', () => {
  beforeEach(() => {
    S.dialogs.length = 0
    S.toasts.length = 0
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('says why a refused delete did not happen', async () => {
    S.refuse = permissionError('Not permitted to delete this file')
    const { close, emitted } = await confirm('Delete Attachment')
    expect(S.toasts).toEqual(['Not permitted to delete this file'])
    expect(close).not.toHaveBeenCalled()
    expect(emitted.reload).toBeUndefined()
  })

  it('says why a refused privacy change did not happen', async () => {
    S.refuse = permissionError('Not permitted to change this file')
    const { close } = await confirm('Make Public')
    expect(S.toasts).toEqual(['Not permitted to change this file'])
    expect(close).not.toHaveBeenCalled()
  })
})
