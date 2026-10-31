import { describe, expect, it } from 'vitest'
import { CRMTask } from '@/doctypes/crm_task/form'
import { FCRMNote } from '@/doctypes/fcrm_note/form'

// The blank "new" document and its controller outlive the modal, so a Create
// opened from a deal and cancelled hands its action to the next Create.
describe.each([
  ['CRM Task', CRMTask],
  ['FCRM Note', FCRMNote],
])('%s form actions', (_, Form) => {
  const render = (controller, doc) => {
    controller.doc = doc
    controller.onRender()
  }

  it('offers the linked record', () => {
    const form = new Form()
    render(form, {
      reference_doctype: 'CRM Deal',
      reference_docname: 'CRM-DEAL-1',
    })
    expect(form.actions.map((a) => a.label)).toEqual(['Open Deal'])
  })

  it('drops the action once the document has no linked record', () => {
    const form = new Form()
    render(form, {
      reference_doctype: 'CRM Deal',
      reference_docname: 'CRM-DEAL-1',
    })
    render(form, { reference_doctype: '', reference_docname: '' })
    expect(form.actions).toEqual([])
  })

  it("leaves another script's actions alone", () => {
    const form = new Form()
    const custom = { name: 'Custom', label: 'Custom' }
    form.actions = [custom]
    render(form, {})
    expect(form.actions).toEqual([custom])
  })
})
