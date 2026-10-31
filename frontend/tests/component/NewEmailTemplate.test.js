import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fakeBackend } from './fakeBackend.js'
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
import NewEmailTemplate from '@/components/Settings/EmailTemplate/NewEmailTemplate.vue'

vi.stubGlobal('localStorage', memoryStorage())

let backend
beforeEach(() => {
  backend = fakeBackend()
  backend.handlers['frappe.client.get_list'] = () => []
  backend.handlers['frappe.client.insert'] = ({ doc }) => ({ ...doc })
  toast.success.mockReset()
})

function mountNew(templateData = {}) {
  const templates = createListResource({
    doctype: 'Email Template',
    fields: ['name'],
  })
  return mount(NewEmailTemplate, {
    props: { templateData },
    stubs: { Button, ErrorMessage },
    plugins: [{ install: (app) => app.provide('templates', templates) }],
  })
}

function inserted() {
  return backend.log.filter((r) => r.url === 'frappe.client.insert')
}

describe('NewEmailTemplate', () => {
  it('saves an HTML template with use_html set (FE-56)', async () => {
    const w = mountNew()
    await flushPromises()
    setValue(byLabel(w.el, 'Name'), 'Quote follow-up')
    setValue(byLabel(w.el, 'Subject'), 'Your quote {{ name }}')
    setValue(byLabel(w.el, 'Content Type'), 'HTML')
    await flushPromises()
    setValue(byLabel(w.el, 'Content'), '<p>Dear {{ lead_name }}</p>')
    buttonByText(w.el, 'Save').click()
    await flushPromises()

    const [{ params }] = inserted()
    expect(params.doc).toMatchObject({
      response_html: '<p>Dear {{ lead_name }}</p>',
      use_html: 1,
    })
    // the select is the form's own state, not an Email Template field
    expect(params.doc).not.toHaveProperty('content_type')
  })

  it('saves a Rich Text template with use_html cleared', async () => {
    const w = mountNew()
    await flushPromises()
    setValue(byLabel(w.el, 'Name'), 'Welcome')
    setValue(byLabel(w.el, 'Subject'), 'Welcome')
    setValue(byLabel(w.el, 'editor'), '<p>Hi</p>')
    buttonByText(w.el, 'Save').click()
    await flushPromises()
    expect(inserted()[0].params.doc).toMatchObject({
      response: '<p>Hi</p>',
      use_html: 0,
    })
  })

  it('opens a duplicate of an HTML template as HTML (FE-56)', async () => {
    // a row as EmailTemplatePage's list resource returns it: no content_type
    const w = mountNew({
      name: 'Quote follow-up',
      enabled: 1,
      use_html: 1,
      reference_doctype: 'CRM Deal',
      subject: 'Your quote',
      response: '',
      response_html: '<p>Hi</p>',
    })
    await flushPromises()
    expect(byLabel(w.el, 'Content Type').value).toBe('HTML')
    buttonByText(w.el, 'Duplicate').click()
    await flushPromises()
    expect(inserted()[0].params.doc).toMatchObject({
      name: 'Quote follow-up - Copy',
      response_html: '<p>Hi</p>',
      use_html: 1,
    })
  })

  it('shows a fallback when the insert fails without server messages (FE-127)', async () => {
    const w = mountNew()
    await flushPromises()
    setValue(byLabel(w.el, 'Name'), 'Welcome')
    setValue(byLabel(w.el, 'Subject'), 'Welcome')
    setValue(byLabel(w.el, 'editor'), '<p>Hi</p>')
    const failure = new TypeError('Failed to fetch')
    backend.handlers['frappe.client.insert'] = () => {
      throw failure
    }
    const rejections = await collectRejections(() =>
      buttonByText(w.el, 'Save').click(),
    )
    expect(w.el.textContent).toContain('Failed to create template')
    expect(rejections.filter((r) => r !== failure)).toEqual([])
  })
})
