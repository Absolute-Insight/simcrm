import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fakeBackend } from './fakeBackend.js'
import { flushPromises } from './flush.js'
import { mount } from './mount.js'
import { memoryStorage, setValue } from './stubs.js'

const { toast } = vi.hoisted(() => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))
vi.mock('frappe-ui', async (importOriginal) => {
  const { Select, TextInput } = await import('./stubs.js')
  return { ...(await importOriginal()), Select, TextInput, toast }
})

import { Button, createListResource } from 'frappe-ui'
import EmailTemplates from '@/components/Settings/EmailTemplate/EmailTemplates.vue'

vi.stubGlobal('localStorage', memoryStorage())

// 21 templates, newest first; the oldest one is the only quote template
const ROWS = Array.from({ length: 21 }, (_, i) => ({
  name:
    i === 20 ? 'Quote follow-up' : `Template ${String(i + 1).padStart(2, '0')}`,
  subject: `Subject ${i + 1}`,
  enabled: 1,
  use_html: 0,
  reference_doctype: 'CRM Deal',
}))

/** frappe.client.get_list over ROWS: doctype filter, name/subject `like`. */
function getList({ filters, or_filters, limit_start = 0, limit = 20 }) {
  const like = (value, pattern) =>
    value.toLowerCase().includes(pattern.replaceAll('%', '').toLowerCase())
  const doctype = filters?.reference_doctype
  return ROWS.filter(
    (row) =>
      !doctype ||
      (Array.isArray(doctype)
        ? doctype[1].includes(row.reference_doctype)
        : row.reference_doctype === doctype),
  )
    .filter(
      (row) =>
        !or_filters?.length ||
        or_filters.some(([field, , pattern]) => like(row[field], pattern)),
    )
    .slice(limit_start, limit_start + limit)
    .map((row) => ({ ...row }))
}

let backend
beforeEach(() => {
  backend = fakeBackend()
  backend.handlers['frappe.client.get_list'] = getList
  toast.error.mockReset()
})

async function mountList() {
  // as EmailTemplatePage builds it
  const templates = createListResource({
    type: 'list',
    doctype: 'Email Template',
    fields: ['name', 'enabled', 'reference_doctype', 'subject'],
    auto: true,
    filters: { reference_doctype: ['in', ['CRM Lead', 'CRM Deal']] },
    orderBy: 'modified desc',
    pageLength: 20,
  })
  const w = mount(EmailTemplates, {
    stubs: { Button },
    plugins: [{ install: (app) => app.provide('templates', templates) }],
  })
  await flushPromises()
  return { w, templates }
}

const rows = (w) => [...w.el.querySelectorAll('li')].map((li) => li.textContent)

describe('EmailTemplates', () => {
  it('searches the server, not just the page already loaded (FE-128)', async () => {
    const { w } = await mountList()
    expect(rows(w).join('|')).not.toContain('Quote follow-up')

    setValue(w.el.querySelector('[data-label="Search Template"]'), 'quote')
    await flushPromises()
    expect(rows(w).join('|')).toContain('Quote follow-up')
    const last = backend.log.at(-1).params
    expect(last.or_filters).toEqual([
      ['name', 'like', '%quote%'],
      ['subject', 'like', '%quote%'],
    ])

    // a search that matches nothing keeps the box, so it can be cleared
    setValue(w.el.querySelector('[data-label="Search Template"]'), 'zzz')
    await flushPromises()
    expect(w.el.querySelector('[data-label="Search Template"]')).toBeTruthy()
    setValue(w.el.querySelector('[data-label="Search Template"]'), '')
    await flushPromises()
    expect(rows(w)).toHaveLength(20)
  })
})
