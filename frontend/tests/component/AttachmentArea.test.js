import { h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import AttachmentArea from '@/components/Activities/AttachmentArea.vue'

const S = vi.hoisted(() => ({
  dialogs: [],
  toasts: [],
  refuse: null,
  images: false,
}))

vi.mock('frappe-ui', () => ({
  call: () => Promise.reject(S.refuse),
  toast: { error: (m) => S.toasts.push(m) },
}))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog: (d) => S.dialogs.push(d) }),
}))
vi.mock('@/utils', () => ({
  convertSize: (n) => String(n),
  isImage: (type) => S.images && type === 'JPG',
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

// A deal with N phone photos fetched N originals, 3-8 MB each, the moment the
// tab drew: the 44px square had the file itself as its src, eagerly.
describe('AttachmentArea thumbnails', () => {
  beforeEach(() => {
    S.images = true
    return () => (S.images = false)
  })

  const photo = (i, extra = {}) => ({
    ...attachment,
    name: `FILE-${i}`,
    file_name: `site-${i}.jpg`,
    file_url: `/private/files/site-${i}.jpg`,
    file_size: 6_000_000,
    ...extra,
  })

  function thumbnails(attachments) {
    const w = mount(AttachmentArea, {
      props: { attachments },
      stubs: { Button },
    })
    return [...w.el.querySelectorAll('img')]
  }

  it('loads every thumbnail lazily, off the main thread, at a fixed size', () => {
    const imgs = thumbnails([1, 2, 3, 4, 5].map((i) => photo(i)))
    expect(imgs).toHaveLength(5)
    for (const img of imgs) {
      expect(img.getAttribute('loading')).toBe('lazy')
      expect(img.getAttribute('decoding')).toBe('async')
      expect(img.getAttribute('width')).toBe('44')
      expect(img.getAttribute('height')).toBe('44')
    }
  })

  it('draws the small copy when the server sends one, the file otherwise', () => {
    const [small, original] = thumbnails([
      photo(1, { thumbnail_url: '/private/files/site-1_small.jpg' }),
      photo(2, { thumbnail_url: null }),
    ])
    expect(small.getAttribute('src')).toBe('/private/files/site-1_small.jpg')
    expect(original.getAttribute('src')).toBe('/private/files/site-2.jpg')
  })

  it('still opens the original, not the thumbnail', () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const w = mount(AttachmentArea, {
      props: {
        attachments: [
          photo(1, { thumbnail_url: '/private/files/site-1_small.jpg' }),
        ],
      },
      stubs: { Button },
    })
    w.el.querySelector('.activity').click()
    expect(open).toHaveBeenCalledWith(
      '/private/files/site-1.jpg',
      '_blank',
      'noopener',
    )
  })
})
