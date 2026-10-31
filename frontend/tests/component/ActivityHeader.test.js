import { describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { mount } from './mount.js'

vi.mock('@/stores/global', () => ({
  globalStore: () => ({ makeCall() {} }),
}))
vi.mock('@/composables/telephony', async () => ({
  callEnabled: (await import('vue')).ref(false),
}))
vi.mock('@/composables/whatsapp', async () => ({
  whatsappEnabled: (await import('vue')).ref(false),
  whatsappSupported: (await import('vue')).ref(false),
}))

const { default: ActivityHeader } = await import(
  '@/components/Activities/ActivityHeader.vue'
)

describe('ActivityHeader', () => {
  it('sits on the same gutter as the activities under it', () => {
    const { el } = mount(ActivityHeader, {
      props: { title: 'Activity', tabs: [], doc: {}, modelValue: 0 },
      stubs: {
        Button: { render: () => h('button') },
        Dropdown: { render: () => null },
      },
    })
    const header = el.firstElementChild
    expect(header.classList.contains('mx-3')).toBe(true)
    expect(header.classList.contains('sm:mx-10')).toBe(true)
  })
})
