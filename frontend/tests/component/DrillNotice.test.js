import { describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import DrillNotice from '@/components/DrillNotice.vue'

describe('DrillNotice', () => {
  it('says what the list is showing and offers the way back', () => {
    const onClear = vi.fn()
    const w = mount(DrillNotice, {
      props: { message: 'Every lead', actionLabel: 'Back', onClear },
    })
    expect(w.el.textContent).toContain('Every lead')
    const button = w.el.querySelector('button')
    expect(button.textContent).toContain('Back')
    button.click()
    expect(onClear).toHaveBeenCalledOnce()
  })

  it('is announced, since it appears after navigation', () => {
    const w = mount(DrillNotice, {
      props: { message: 'Every lead', actionLabel: 'Back' },
    })
    expect(w.el.querySelector('[role="status"]')).not.toBeNull()
  })
})
