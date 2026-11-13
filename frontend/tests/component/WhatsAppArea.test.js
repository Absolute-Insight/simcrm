import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import WhatsAppArea from '@/components/Activities/WhatsAppArea.vue'

const { blank } = vi.hoisted(() => ({
  blank: () => ({ default: { render: () => null } }),
}))
vi.mock('@/components/IconPicker.vue', blank)
vi.mock('@/components/Icons/CheckIcon.vue', blank)
vi.mock('@/components/Icons/DoubleCheckIcon.vue', blank)
vi.mock('@/components/Icons/DocumentIcon.vue', blank)
vi.mock('@/components/Icons/ReactIcon.vue', blank)
vi.mock('@/utils', () => ({ formatDate: () => '' }))
vi.mock('@framework/ui/telemetry', () => ({
  useTelemetry: () => ({ capture: () => {} }),
}))
vi.mock('frappe-ui', () => ({
  Tooltip: { render: () => null },
  Dropdown: { render: () => null },
  createResource: () => ({}),
  toast: { error: () => {} },
}))

const stub = { render: () => null }

const photo = (i) => ({
  name: `WA-${i}`,
  type: 'Incoming',
  content_type: 'image',
  attach: `/private/files/photo-${i}.jpg`,
  message: '',
  status: 'delivered',
  creation: '2026-10-29 10:00:00',
})

// A chat of site photos fetched every one of them, full size, when the tab
// opened, however far up the conversation they were.
describe('WhatsAppArea images', () => {
  it('loads a photo only when it nears the viewport', () => {
    const w = mount(WhatsAppArea, {
      props: { messages: [1, 2, 3].map(photo) },
      stubs: { Badge: stub, Button: stub },
    })
    const imgs = [...w.el.querySelectorAll('img')]
    expect(imgs.map((img) => img.getAttribute('src'))).toEqual([
      '/private/files/photo-1.jpg',
      '/private/files/photo-2.jpg',
      '/private/files/photo-3.jpg',
    ])
    for (const img of imgs) {
      expect(img.getAttribute('loading')).toBe('lazy')
      expect(img.getAttribute('decoding')).toBe('async')
      expect(img.getAttribute('height')).toBe('160')
    }
  })
})
