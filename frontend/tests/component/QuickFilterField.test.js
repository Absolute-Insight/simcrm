import { describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { mount } from './mount.js'

// The real frappe-ui DatePicker and DateTimePicker; only the Link control
// (which fetches) and the site date format are stubbed.
vi.mock('@/components/Controls/Link.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/utils', () => ({
  getFormat: (_date, _format, onlyDate, onlyTime) =>
    onlyDate && onlyTime ? 'DD-MM-YYYY HH:mm' : 'DD-MM-YYYY',
}))

const QuickFilterField = (await import('@/components/QuickFilterField.vue'))
  .default

const translate = {
  install: (app) => (app.config.globalProperties.__ = globalThis.__),
}

describe('QuickFilterField date filters', () => {
  it.each([
    ['Datetime', '2026-10-30 09:00:00', '30-10-2026 09:00'],
    ['Date', '2026-11-15', '15-11-2026'],
  ])('a %s filter shows its applied value', async (fieldtype, value, shown) => {
    const filter = reactive({
      fieldname: 'due_date',
      fieldtype,
      label: 'Due Date',
      value,
    })
    const w = mount(QuickFilterField, {
      props: { filter },
      plugins: [translate],
    })
    await w.nextTick()
    const input = w.el.querySelector('input')
    expect(input.value).toBe(shown)

    // Cleared elsewhere (the filter popover, a view switch): no stale date.
    filter.value = ''
    await w.nextTick()
    await w.nextTick()
    expect(w.el.querySelector('input').value).toBe('')
    w.unmount()
  })
})
