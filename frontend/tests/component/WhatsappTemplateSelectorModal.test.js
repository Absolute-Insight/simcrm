import { describe, expect, it, vi } from 'vitest'
import { setConfig } from 'frappe-ui'
import { mount } from './mount.js'
import { flush, modalStubs, translation } from './stubs.js'
import WhatsappTemplateSelectorModal from '@/components/Modals/WhatsappTemplateSelectorModal.vue'

// frappe-ui's real createListResource, with the fetcher recording what is
// asked for and answering with one template per doctype.
const S = vi.hoisted(() => ({ asked: [] }))

vi.mock('frappe-ui/experimental', () => ({
  TextEditor: { name: 'TextEditor', render: () => null },
}))

setConfig('resourceFetcher', (options) => {
  const [doctype] = options.params.filters.for_doctype[1]
  S.asked.push(doctype)
  return Promise.resolve([
    { name: `${doctype} welcome`, template: 'Hi', footer: '' },
  ])
})

async function openOn(doctype) {
  const w = mount(WhatsappTemplateSelectorModal, {
    props: { modelValue: true, doctype },
    stubs: { ...modalStubs, TextInput: { render: () => null } },
    plugins: [translation],
  })
  await flush()
  const shown = w.el.textContent
  w.unmount()
  return shown
}

describe('WhatsApp template picker', () => {
  it("shows a deal's templates after a lead's were shown", async () => {
    expect(await openOn('CRM Lead')).toContain('CRM Lead welcome')
    expect(await openOn('CRM Deal')).toContain('CRM Deal welcome')
    expect(S.asked).toEqual(['CRM Lead', 'CRM Deal'])
  })
})
