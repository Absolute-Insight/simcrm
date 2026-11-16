import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { mount } from '../mount.js'
import { failure, field, flush } from './standIns.js'

const backend = vi.hoisted(() => ({ handlers: {}, log: [], toasts: [] }))
vi.mock('frappe-ui', async (importOriginal) =>
  (await import('./standIns.js')).frappeUi(importOriginal, backend),
)
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    getUser: (email) => ({ full_name: { 'b@x.test': 'Rep B' }[email] }),
  }),
}))

const { default: DuplicateContacts } = await import(
  '@/components/Settings/DuplicateContacts.vue'
)

const RouterLink = {
  props: ['to'],
  setup:
    (props, { slots }) =>
    () =>
      h('a', { 'data-to': JSON.stringify(props.to) }, slots.default?.()),
}

const contact = (name, extra = {}) => ({
  name,
  full_name: name,
  company_name: 'Impala',
  owner: 'a@x.test',
  customer_owner: 'b@x.test',
  deals: 0,
  creation: '2026-11-01 09:00:00',
  ...extra,
})

const page = (groups, total = groups.length) => ({ total, groups })

const loads = () =>
  backend.log.filter((r) => r.url === 'crm.api.contact.get_duplicate_contacts')

beforeEach(() => {
  backend.log.length = 0
  backend.toasts.length = 0
  backend.handlers = {
    'crm.api.contact.get_duplicate_contacts': () =>
      page([
        {
          email: 'buyer@impala.test',
          contacts: [contact('Jane'), contact('Jane-1', { deals: 2 })],
        },
      ]),
    'crm.api.contact.merge_duplicate_contacts': ({ target }) => target,
  }
})

const render = () => mount(DuplicateContacts, { stubs: { RouterLink } })

describe('Duplicate contacts', () => {
  it('lists each shared address with its contacts and their account owner', async () => {
    const { el } = render()
    await flush()

    expect(el.textContent).toContain('buyer@impala.test')
    expect(el.textContent).toContain('Jane-1')
    expect(el.textContent).toContain('Rep B')
    expect(loads()[0].params).toEqual({ start: 0, page_length: 20 })
  })

  it('merges the others into the one kept, after asking', async () => {
    const { el } = render()
    await flush()

    el.querySelectorAll('[data-label="Keep"]')[1].click()
    await flush()
    expect(backend.log.map((r) => r.url)).not.toContain(
      'crm.api.contact.merge_duplicate_contacts',
    )
    expect(el.textContent).toContain('Merge Jane into Jane-1?')

    field(el, 'Merge').click()
    await flush()

    const merge = backend.log.find(
      (r) => r.url === 'crm.api.contact.merge_duplicate_contacts',
    )
    expect(merge.params).toEqual({ target: 'Jane-1', sources: ['Jane'] })
    expect(backend.toasts).toContainEqual(['success', 'Contacts merged'])
    expect(loads()).toHaveLength(2)
  })

  it("toasts the server's refusal and keeps the dialog open", async () => {
    backend.handlers['crm.api.contact.merge_duplicate_contacts'] = () => {
      throw failure('Jane is linked to Acumatica')
    }
    const { el } = render()
    await flush()

    el.querySelectorAll('[data-label="Keep"]')[0].click()
    await flush()
    field(el, 'Merge').click()
    await flush()

    expect(backend.toasts).toContainEqual([
      'error',
      'Jane is linked to Acumatica',
    ])
    expect(field(el, 'Merge')).toBeTruthy()
  })

  it('pages through the addresses', async () => {
    backend.handlers['crm.api.contact.get_duplicate_contacts'] = ({ start }) =>
      page(
        [
          {
            email: `p${start}@impala.test`,
            contacts: [contact('A'), contact('B')],
          },
        ],
        45,
      )
    const { el } = render()
    await flush()
    expect(el.textContent).toContain('1–20 of 45 addresses')
    expect(field(el, 'Previous').disabled).toBe(true)

    field(el, 'Next').click()
    await flush()
    expect(loads().at(-1).params).toEqual({ start: 20, page_length: 20 })
    expect(el.textContent).toContain('p20@impala.test')
  })

  it('says so when there are none', async () => {
    backend.handlers['crm.api.contact.get_duplicate_contacts'] = () => page([])
    const { el } = render()
    await flush()
    expect(el.textContent).toContain('No duplicate contacts')
  })
})
