import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mount } from '../mount.js'
import { flush } from './standIns.js'

const backend = vi.hoisted(() => ({ handlers: {}, log: [], toasts: [] }))
vi.mock('frappe-ui', async (importOriginal) => {
  const { defineComponent } = await import('vue')
  // the popover's content is always open here, so the search list is drivable
  const Popover = defineComponent({
    setup:
      (_, { slots }) =>
      () => [slots.trigger?.({}), slots.default?.({ close() {} })],
  })
  return (await import('./standIns.js')).frappeUi(importOriginal, backend, {
    Popover,
  })
})
const CRM_USERS = [
  {
    name: 'tnkosi@example.com',
    email: 'tnkosi@example.com',
    full_name: 'Thabo Nkosi',
  },
  {
    name: 'pvdm@example.com',
    email: 'pvdm@example.com',
    full_name: 'Pieter van der Merwe',
  },
]
vi.mock('@/stores/users', async () => {
  const { reactive } = await import('vue')
  const byName = Object.fromEntries(CRM_USERS.map((u) => [u.name, u]))
  return {
    usersStore: () => ({
      users: reactive({ data: { crmUsers: CRM_USERS } }),
      getUser: (email) =>
        byName[email] || { name: email, email, full_name: email },
    }),
  }
})
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog: () => {} }),
}))
vi.mock('@/stores/help', () => ({ openHelpCenter: () => {} }))
const inert = vi.hoisted(() => () => ({ default: { render: () => null } }))
vi.mock(
  '@/components/Settings/AssignmentRules/AssignmentRulesSection.vue',
  inert,
)
vi.mock('@/components/Settings/AssignmentRules/AssignmentSchedule.vue', inert)
vi.mock('@/components/ui/ConfirmDialog.vue', inert)

const { default: AssignmentRuleView } = await import(
  '@/components/Settings/AssignmentRules/AssignmentRuleView.vue'
)

const RULE = {
  name: 'Leads JHB',
  description: 'Johannesburg leads',
  priority: 1,
  disabled: 0,
  rule: 'Round Robin',
  document_type: 'CRM Lead',
  assignment_days: [{ day: 'Monday' }],
  users: [
    { name: 'r1', user: 'tnkosi@example.com' },
    { name: 'r2', user: 'pvdm@example.com' },
  ],
  // Round Robin's pointer, which frappe moves on every assignment
  last_user: 'tnkosi@example.com',
  assign_condition: "doc.status == 'New'",
  assign_condition_json: '[["status","equals","New"]]',
  unassign_condition: '',
  unassign_condition_json: '[]',
}

async function mountRule(rule) {
  backend.handlers['frappe.client.get'] = () => structuredClone(rule)
  const context = {
    install(app) {
      app.provide('step', ref({ screen: 'view', data: { name: rule.name } }))
      app.provide('updateStep', () => {})
    },
  }
  const wrapper = mount(AssignmentRuleView, { plugins: [context] })
  await flush()
  return wrapper
}

const chip = (el, name) =>
  [...el.querySelectorAll('div')].find(
    (d) =>
      d.classList.contains('select-none') &&
      d.textContent.includes(name) &&
      !d.querySelector('li'),
  )

beforeEach(() => {
  backend.handlers = {}
  backend.log.length = 0
})

describe('AssigneeRules', () => {
  it('marks the assignee Round Robin assigned to last', async () => {
    const { el } = await mountRule(RULE)
    expect(chip(el, 'Thabo Nkosi').textContent).toContain('Last')
    expect(chip(el, 'Pieter van der Merwe').textContent).not.toContain('Last')
  })

  it('finds an assignee whatever the case of the search, and by email', async () => {
    const { el } = await mountRule({ ...RULE, users: [] })
    const input = el.querySelector('input[placeholder="Search"]')
    async function search(text) {
      input.value = text
      input.dispatchEvent(new Event('input'))
      await new Promise((resolve) => setTimeout(resolve, 350)) // debounced 300ms
      await flush()
      return [...el.querySelectorAll('li')].map((li) => li.textContent)
    }
    for (const text of ['Thabo', 'thabo', 'NKOSI', 'tnkosi@']) {
      const options = await search(text)
      expect(
        options.some((o) => o.includes('Thabo Nkosi')),
        `${text}: ${JSON.stringify(options)}`,
      ).toBe(true)
      expect(options.some((o) => o.includes('Pieter'))).toBe(false)
    }
  })
})
