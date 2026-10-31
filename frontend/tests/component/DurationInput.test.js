import { describe, expect, it } from 'vitest'
import { mount } from './mount.js'
import DurationInput from '@/components/Controls/DurationInput.vue'

// The real DurationInput and frappe-ui TextInput.
function open(value) {
  const w = mount(DurationInput, { props: { value } })
  return { ...w, input: w.el.querySelector('input') }
}

async function type(w, text) {
  w.input.focus()
  await w.nextTick()
  w.input.value = text
  w.input.dispatchEvent(new Event('input', { bubbles: true }))
  await w.nextTick()
}

const press = (w, key) =>
  w.input.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))

describe('DurationInput keyboard handling', () => {
  it('selects the value on focus, so typing replaces it', async () => {
    const w = open(3600)
    w.input.focus()
    await w.nextTick()
    await w.nextTick()
    expect(w.input.value).toBe('1h')
    expect([w.input.selectionStart, w.input.selectionEnd]).toEqual([0, 2])
    w.unmount()
  })

  it('Escape cancels the edit, and leaving the field afterwards saves nothing', async () => {
    const w = open(3600)
    await type(w, '5h')
    press(w, 'Escape')
    await w.nextTick()
    expect(document.activeElement).not.toBe(w.input)
    w.input.blur() // the user clicks elsewhere
    await w.nextTick()
    expect(w.emitted.change).toBeUndefined()
    expect(w.input.value).toBe('1h')
    w.unmount()
  })

  it('Enter commits exactly once', async () => {
    const w = open(3600)
    await type(w, '2h')
    press(w, 'Enter')
    await w.nextTick()
    expect(document.activeElement).not.toBe(w.input)
    w.input.blur()
    await w.nextTick()
    expect(w.emitted.change).toEqual([[7200]])
    w.unmount()
  })

  it('leaving the field commits the edit once', async () => {
    const w = open(3600)
    await type(w, '90m')
    w.input.blur()
    await w.nextTick()
    expect(w.emitted.change).toEqual([[5400]])
    w.unmount()
  })
})
