import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '../mount.js'
import { failure, field, flush } from './standIns.js'

const backend = vi.hoisted(() => ({ handlers: {}, log: [], toasts: [] }))
vi.mock('frappe-ui', async (importOriginal) =>
  (await import('./standIns.js')).frappeUi(importOriginal, backend),
)
const session = vi.hoisted(() => ({ user: 'mgr@x.test', admin: false }))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    isManager: () => true,
    isAdmin: () => session.admin,
    getUser: () => ({ name: session.user }),
  }),
}))

const { default: Quotas } = await import('@/components/Settings/Quotas.vue')

const YEAR = new Date().getFullYear()
const months = (year) =>
  Array.from(
    { length: 12 },
    (_, i) => `${year}-${String(i + 1).padStart(2, '0')}-01`,
  )
const gridFor = (year) => ({
  year,
  months: months(year),
  currency: 'ZAR',
  rows: [
    // visible_reps always holds the caller, so a manager sees their own row
    { user: 'mgr@x.test', full_name: 'Manager', quota: {}, actual: 0 },
    {
      user: 'ann@x.test',
      full_name: 'Ann',
      quota: { [`${year}-01-01`]: 50000 },
      actual: 0,
    },
    {
      user: 'rep@x.test',
      full_name: 'Rep',
      quota: { [`${year}-02-01`]: 100000 },
      actual: 0,
    },
  ],
})

const cell = (el, who, month) =>
  el.querySelector(`input[aria-label="${who} ${month}"]`)
const focus = (input) => input.dispatchEvent(new FocusEvent('focus'))
const blur = (input) => input.dispatchEvent(new FocusEvent('blur'))
function type(input, text) {
  input.value = text
  input.dispatchEvent(new Event('input'))
}
const saves = () =>
  backend.log.filter((r) => r.url === 'crm.api.quota.set_quota')

beforeEach(() => {
  backend.log.length = 0
  backend.toasts.length = 0
  session.admin = false
  backend.handlers = {
    'crm.api.quota.get_quota_grid': ({ year }) => gridFor(Number(year)),
    'crm.api.quota.set_quota': ({ amount }) => ({ amount }),
  }
})

describe('Sales Targets grid', () => {
  it('a save refused elsewhere does not overwrite the cell being typed in', async () => {
    const { el } = mount(Quotas)
    await flush()

    // Ann's January goes out and is held; the manager moves on to Rep's February
    let refuse
    backend.handlers['crm.api.quota.set_quota'] = () =>
      new Promise((_, reject) => (refuse = reject))
    const annJan = cell(el, 'Ann', `${YEAR}-01-01`)
    focus(annJan)
    type(annJan, '60000')
    blur(annJan)
    await flush()

    backend.handlers['crm.api.quota.set_quota'] = ({ amount }) => ({ amount })
    const repFeb = cell(el, 'Rep', `${YEAR}-02-01`)
    focus(repFeb)
    expect(repFeb.value).toBe('100000')
    type(repFeb, '120000')

    // the refusal rolls Ann's January back and re-renders the grid
    refuse(failure('Ann is not on your team.'))
    await flush()
    expect(cell(el, 'Ann', `${YEAR}-01-01`).value).toBe('50K')
    expect(repFeb.value).toBe('120000')

    blur(repFeb)
    await flush()
    const rep = saves().filter((r) => r.params.user === 'rep@x.test')
    expect(rep.map((r) => r.params.amount)).toEqual([120000])
    expect(repFeb.value).toBe('120K')
  })

  it("leaves a manager's own row read-only, since only an administrator may set it", async () => {
    const { el } = mount(Quotas)
    await flush()
    expect(cell(el, 'Manager', `${YEAR}-01-01`)).toBeNull()
    expect(cell(el, 'Rep', `${YEAR}-01-01`)).not.toBeNull()
  })

  it('lets an administrator set their own target', async () => {
    session.admin = true
    const { el } = mount(Quotas)
    await flush()
    expect(cell(el, 'Manager', `${YEAR}-01-01`)).not.toBeNull()
  })

  it('reads a target typed in the compact notation the grid shows', async () => {
    const { el } = mount(Quotas)
    await flush()
    const repMar = cell(el, 'Rep', `${YEAR}-03-01`)
    focus(repMar)
    type(repMar, '300K')
    blur(repMar)
    await flush()
    expect(saves().map((r) => r.params.amount)).toEqual([300000])
  })

  it('refuses a target it cannot read rather than saving a different one', async () => {
    const { el } = mount(Quotas)
    await flush()
    const repMar = cell(el, 'Rep', `${YEAR}-03-01`)
    focus(repMar)
    type(repMar, '300 thousand')
    blur(repMar)
    await flush()
    expect(saves()).toEqual([])
    expect(backend.toasts.map(([kind]) => kind)).toEqual(['error'])
  })

  it('shows, and edits, the year in the header when responses land out of order', async () => {
    const pending = {}
    backend.handlers['crm.api.quota.get_quota_grid'] = ({ year }) => {
      const y = Number(year)
      if (y === YEAR) return gridFor(y)
      return new Promise((resolve) => (pending[y] = () => resolve(gridFor(y))))
    }
    const { el } = mount(Quotas)
    await flush()
    field(el, 'Next year').click()
    await flush()
    field(el, 'Next year').click()
    await flush()
    // the later request answers first, the earlier one after it
    pending[YEAR + 2]()
    await flush()
    pending[YEAR + 1]()
    await flush()

    const header = el.querySelector('.w-14').textContent.trim()
    expect(header).toBe(String(YEAR + 2))
    const repJan = cell(el, 'Rep', `${YEAR + 2}-01-01`)
    expect(repJan).not.toBeNull()
    focus(repJan)
    type(repJan, '50000')
    blur(repJan)
    await flush()
    expect(saves().at(-1).params.period_start).toBe(`${YEAR + 2}-01-01`)
  })

  it('ignores a failure of a year already moved past', async () => {
    const pending = {}
    backend.handlers['crm.api.quota.get_quota_grid'] = ({ year }) => {
      const y = Number(year)
      if (y === YEAR) return gridFor(y)
      return new Promise(
        (resolve, reject) => (pending[y] = { resolve, reject }),
      )
    }
    const { el } = mount(Quotas)
    await flush()
    field(el, 'Next year').click()
    await flush()
    field(el, 'Next year').click()
    await flush()
    pending[YEAR + 2].resolve(gridFor(YEAR + 2))
    await flush()
    pending[YEAR + 1].reject(failure('Request timed out'))
    await flush()
    expect(el.textContent).not.toContain('Could not load the sales targets')
    expect(cell(el, 'Rep', `${YEAR + 2}-01-01`)).not.toBeNull()
  })

  it('does not show the previous year under the new heading while it loads', async () => {
    let answer
    backend.handlers['crm.api.quota.get_quota_grid'] = ({ year }) =>
      Number(year) === YEAR
        ? gridFor(YEAR)
        : new Promise((resolve) => (answer = () => resolve(gridFor(year))))
    const { el } = mount(Quotas)
    await flush()
    field(el, 'Next year').click()
    await flush()
    expect(el.querySelector('.w-14').textContent.trim()).toBe(String(YEAR + 1))
    expect(cell(el, 'Rep', `${YEAR}-01-01`)).toBeNull()
    answer()
    await flush()
    expect(cell(el, 'Rep', `${YEAR + 1}-01-01`)).not.toBeNull()
  })
})
