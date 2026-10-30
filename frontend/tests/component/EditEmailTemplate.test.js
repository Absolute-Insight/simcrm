import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fakeBackend, frappeError } from './fakeBackend.js'
import { collectRejections, flushPromises } from './flush.js'
import { mount } from './mount.js'
import { byLabel, buttonByText, memoryStorage, setValue } from './stubs.js'

const { toast } = vi.hoisted(() => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))
vi.mock('frappe-ui', async (importOriginal) => {
  const { FormControl } = await import('./stubs.js')
  return { ...(await importOriginal()), FormControl, toast }
})
vi.mock('frappe-ui/experimental', async () => {
  const { TextEditor } = await import('./stubs.js')
  return { TextEditor }
})

import { Button, ErrorMessage, createListResource } from 'frappe-ui'
import EditEmailTemplate from '@/components/Settings/EmailTemplate/EditEmailTemplate.vue'

vi.stubGlobal('localStorage', memoryStorage())

const TEMPLATE = {
  name: 'Payment Reminder',
  enabled: 1,
  use_html: 0,
  reference_doctype: 'CRM Deal',
  subject: 'Reminder for {{ name }}',
  response: '<p>Dear customer</p>',
  response_html: null,
}

let backend, db
beforeEach(() => {
  db = { [TEMPLATE.name]: { ...TEMPLATE } }
  backend = fakeBackend()
  backend.handlers['frappe.client.get_list'] = () =>
    Object.values(db).map((t) => ({ ...t }))
  backend.handlers['frappe.client.rename_doc'] = ({ old_name, new_name }) => {
    if (!db[old_name]) {
      throw frappeError(`Email Template ${old_name} not found`)
    }
    db[new_name] = { ...db[old_name], name: new_name }
    delete db[old_name]
    return new_name
  }
  backend.handlers['frappe.client.set_value'] = ({ name, fieldname }) => {
    if (!db[name]) throw frappeError(`Email Template ${name} not found`)
    if (/\{\{[^}]*$/.test(fieldname.subject)) {
      throw frappeError('Syntax error in template')
    }
    Object.assign(db[name], fieldname)
    return { ...db[name] }
  }
})

function mountEdit() {
  const templates = createListResource({
    doctype: 'Email Template',
    fields: ['name'],
    auto: true,
  })
  return mount(EditEmailTemplate, {
    props: { templateData: { ...TEMPLATE } },
    stubs: { Button, ErrorMessage },
    plugins: [{ install: (app) => app.provide('templates', templates) }],
  })
}

async function save(w) {
  return collectRejections(() => buttonByText(w.el, 'Save').click())
}

describe('EditEmailTemplate', () => {
  it('saves under the new name after a rename whose field update failed (FE-124)', async () => {
    const w = mountEdit()
    await flushPromises()
    setValue(byLabel(w.el, 'Name'), 'Payment Reminder v2')
    setValue(byLabel(w.el, 'Subject'), 'Reminder for {{ name ')
    await flushPromises()
    await save(w)
    expect(Object.keys(db)).toEqual(['Payment Reminder v2'])
    expect(w.el.textContent).toContain('Syntax error in template')

    setValue(byLabel(w.el, 'Subject'), 'Reminder for {{ name }} - final')
    await flushPromises()
    await save(w)
    const renames = backend.log.filter(
      (r) => r.url === 'frappe.client.rename_doc',
    )
    expect(renames).toHaveLength(1)
    expect(db['Payment Reminder v2'].subject).toBe(
      'Reminder for {{ name }} - final',
    )
    expect(w.el.textContent).not.toContain('not found')
    expect(w.emitted.updateStep).toEqual([['template-list']])
  })

  it('shows a fallback when a call fails without server messages (FE-127)', async () => {
    const offline = new TypeError('Failed to fetch')
    backend.handlers['frappe.client.rename_doc'] = () => {
      throw offline
    }
    backend.handlers['frappe.client.set_value'] = () => {
      throw offline
    }
    const w = mountEdit()
    await flushPromises()

    setValue(byLabel(w.el, 'Name'), 'Payment Reminder v2')
    await flushPromises()
    let rejections = await save(w)
    expect(w.el.textContent).toContain('Failed to rename template')
    expect(rejections.filter((r) => r !== offline)).toEqual([])

    setValue(byLabel(w.el, 'Name'), TEMPLATE.name)
    setValue(byLabel(w.el, 'Subject'), 'Reminder')
    await flushPromises()
    rejections = await save(w)
    expect(w.el.textContent).toContain('Failed to update template')
    expect(rejections.filter((r) => r !== offline)).toEqual([])
  })
})
