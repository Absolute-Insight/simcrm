import { describe, expect, it } from 'vitest'
import { mount } from './mount.js'
import FormattedInput from '@/components/Controls/FormattedInput.vue'

describe('FormattedInput', () => {
  // frappe-ui v1's TextInput exposes `inputElement`, not `el`, so the
  // select-on-focus silently did nothing and an edit landed inside the
  // formatted text instead of replacing it.
  it('selects the whole value on focus, so typing replaces it', async () => {
    const w = mount(FormattedInput, {
      props: {
        type: 'text',
        value: '50221.12',
        formattedValue: 'ZAR 50 221.12',
      },
    })
    const input = w.el.querySelector('input')
    expect(input.value).toBe('ZAR 50 221.12')
    input.focus()
    input.dispatchEvent(new Event('focus'))
    await w.nextTick()
    await w.nextTick()
    expect(input.value).toBe('50221.12')
    expect([input.selectionStart, input.selectionEnd]).toEqual([
      0,
      input.value.length,
    ])
    w.unmount()
  })
})
