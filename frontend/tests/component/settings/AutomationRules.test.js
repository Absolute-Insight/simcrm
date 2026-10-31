import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '../mount.js'
import { enter, failure, field, flush } from './standIns.js'

// frappe-ui's real list resource against an in-memory backend: what goes wrong
// below is what the pane sends and when it reloads (see standIns.js).
const backend = vi.hoisted(() => ({ handlers: {}, log: [], toasts: [] }))
vi.mock('frappe-ui', async (importOriginal) =>
  (await import('./standIns.js')).frappeUi(importOriginal, backend),
)
vi.mock('@/components/ui/ConfirmDialog.vue', () => ({
  default: { render: () => null },
}))

const { default: AutomationRules } = await import(
  '@/components/Settings/AutomationRules.vue'
)

const RULE = {
  name: 'Negotiation follow-up',
  title: 'Negotiation follow-up',
  enabled: 1,
  document_type: 'CRM Deal',
  trigger: 'Status Changed',
  to_status: 'Negotiation',
  condition: '',
  action: 'Create Task',
  title_template: 'Follow up',
  description_template: '',
  task_priority: 'Medium',
  suggestion_score: 60,
  due_in_days: 2,
  assign_to_owner: 1,
}

let db
function installBackend({ refuseFirstSetValue = false } = {}) {
  db = { [RULE.name]: { ...RULE } }
  let setValues = 0
  backend.handlers['frappe.client.get_list'] = ({ doctype }) => {
    if (doctype === 'CRM Automation Rule')
      return Object.values(db).map((r) => ({ ...r }))
    if (doctype === 'CRM Deal Status')
      return [{ name: 'Qualification' }, { name: 'Negotiation' }]
    if (doctype === 'CRM Lead Status')
      return [{ name: 'New' }, { name: 'Contacted' }]
    throw new Error(`unexpected list ${doctype}`)
  }
  backend.handlers['frappe.client.rename_doc'] = ({ old_name, new_name }) => {
    if (!db[old_name])
      throw failure(`CRM Automation Rule ${old_name} not found`)
    db[new_name] = { ...db[old_name], name: new_name, title: new_name }
    delete db[old_name]
    return new_name
  }
  backend.handlers['frappe.client.set_value'] = ({ name, fieldname }) => {
    setValues += 1
    if (!db[name]) throw failure(`CRM Automation Rule ${name} not found`)
    if (refuseFirstSetValue && setValues === 1)
      throw failure('Invalid condition: invalid syntax')
    Object.assign(db[name], fieldname)
    return { ...db[name] }
  }
  backend.handlers['frappe.client.insert'] = ({ doc }) => {
    db[doc.title] = { ...doc, name: doc.title }
    return { ...db[doc.title] }
  }
}

const saved = () =>
  backend.log.filter((r) => r.url === 'frappe.client.insert').at(-1)?.params.doc

beforeEach(() => {
  backend.handlers = {}
  backend.log.length = 0
  backend.toasts.length = 0
})

describe('AutomationRules editor', () => {
  it('a rename whose set_value was refused saves on the retry, under the new name', async () => {
    installBackend({ refuseFirstSetValue: true })
    const { el } = mount(AutomationRules)
    await flush()
    ;[...el.querySelectorAll('button')]
      .find((b) => b.textContent.includes(RULE.title))
      .click()
    await flush()
    await enter(el, 'Name', 'Negotiation follow-up v2')
    field(el, 'Save rule').click()
    await flush()
    // the rename landed and the set_value behind it did not
    expect(Object.keys(db)).toEqual(['Negotiation follow-up v2'])
    expect(
      el.querySelector('[data-stub="ErrorMessage"]').textContent,
    ).toContain('Invalid condition')

    field(el, 'Save rule').click()
    await flush()
    const renames = backend.log.filter(
      (r) => r.url === 'frappe.client.rename_doc',
    )
    expect(renames).toHaveLength(1)
    expect(el.querySelector('[data-stub="Dialog"]')).toBeNull()
    expect(db['Negotiation follow-up v2'].title).toBe(
      'Negotiation follow-up v2',
    )
  })

  it('reloads the list after a half-applied rename, so reopening the rule edits it by its new name', async () => {
    installBackend({ refuseFirstSetValue: true })
    const { el } = mount(AutomationRules)
    await flush()
    ;[...el.querySelectorAll('button')]
      .find((b) => b.textContent.includes(RULE.title))
      .click()
    await flush()
    await enter(el, 'Name', 'Renamed')
    field(el, 'Save rule').click()
    await flush()
    field(el, 'Cancel').click()
    await flush()

    const row = [...el.querySelectorAll('button')].find((b) =>
      b.textContent.includes('Renamed'),
    )
    expect(row).toBeTruthy()
    row.click()
    await flush()
    field(el, 'Save rule').click()
    await flush()
    expect(el.querySelector('[data-stub="Dialog"]')).toBeNull()
    expect(
      backend.log.filter((r) => r.url === 'frappe.client.rename_doc'),
    ).toHaveLength(1)
  })

  it('switching "Applies to" drops a status of the other document type', async () => {
    installBackend()
    const { el } = mount(AutomationRules)
    await flush()
    field(el, 'New rule').click()
    await flush()
    await enter(el, 'Name', 'Lead contacted')
    await enter(el, 'Status becomes', 'Negotiation')
    await enter(el, 'Applies to', 'CRM Lead')
    field(el, 'Save rule').click()
    await flush()
    expect(saved().document_type).toBe('CRM Lead')
    expect(saved().to_status).toBe('')
  })

  it('opening a rule keeps its status, though that sets "Applies to" too', async () => {
    installBackend()
    db['Lead rule'] = {
      ...RULE,
      name: 'Lead rule',
      title: 'Lead rule',
      document_type: 'CRM Lead',
      to_status: 'Contacted',
    }
    const { el } = mount(AutomationRules)
    await flush()
    ;[...el.querySelectorAll('button')]
      .find((b) => b.textContent.includes('Lead rule'))
      .click()
    await flush()
    expect(field(el, 'Status becomes').value).toBe('Contacted')
    field(el, 'Save rule').click()
    await flush()
    const sent = backend.log.find((r) => r.url === 'frappe.client.set_value')
    expect(sent.params.fieldname.to_status).toBe('Contacted')
  })

  it('switching "When" to Created does not save the hidden status filter', async () => {
    installBackend()
    const { el } = mount(AutomationRules)
    await flush()
    field(el, 'New rule').click()
    await flush()
    await enter(el, 'Name', 'New deal welcome task')
    await enter(el, 'Status becomes', 'Negotiation')
    await enter(el, 'When', 'Created')
    expect(field(el, 'Status becomes')).toBeNull()
    field(el, 'Save rule').click()
    await flush()
    expect(saved().trigger).toBe('Created')
    expect(saved().to_status).toBe('')
  })
})
