import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '../mount.js'
import { flush } from './standIns.js'

const backend = vi.hoisted(() => ({ handlers: {}, log: [], toasts: [] }))
vi.mock('frappe-ui', async (importOriginal) =>
  (await import('./standIns.js')).frappeUi(importOriginal, backend),
)
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ isAdmin: () => true }),
}))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog: () => {} }),
}))

const { default: AccessControl } = await import(
  '@/components/Settings/AccessControl.vue'
)

let held = null
const visibility = () => ({
  role: 'System Manager',
  hidden: [],
  matrix: { 'Sales Manager': [], 'Sales User': [] },
})

beforeEach(() => {
  held = null
  backend.log.length = 0
  backend.handlers = {
    'crm.api.access.get_visibility': () =>
      held ? held.then(visibility) : visibility(),
    'crm.api.access.get_data_access': () => ({
      enable_sales_hierarchy: 0,
      manager_outside_hierarchy: 'All records',
      hierarchy_size: 0,
    }),
    'crm.api.access.set_visibility': ({ role, hidden }) => ({ role, hidden }),
  }
})

// the surface matrix, not the skeleton (which is a <table> too)
const matrix = (el) =>
  [...el.querySelectorAll('table')].find((t) =>
    t.textContent.includes('Surface'),
  )
const repSwitches = (el) =>
  [...el.querySelectorAll('tbody button[role="switch"]')].filter(
    (b) => !b.disabled,
  )

describe('AccessControl surface matrix', () => {
  it('keeps the matrix, and where it was scrolled to, while a toggle refreshes it', async () => {
    const { el } = mount(AccessControl, { plugins: [createPinia()] })
    await flush()
    const scroller = matrix(el).parentElement
    scroller.scrollTop = 900
    const switches = repSwitches(el)
    expect(switches.length).toBeGreaterThan(1)

    let release
    held = new Promise((resolve) => (release = resolve))
    switches.at(-1).click()
    await flush()
    expect(
      backend.log.some((r) => r.url === 'crm.api.access.set_visibility'),
    ).toBe(true)
    // the re-read is in flight: the table is still the one on screen
    expect(matrix(el)?.parentElement).toBe(scroller)
    // and its switches wait for it, so nothing is saved from a stale row
    expect(repSwitches(el)).toHaveLength(0)

    release()
    await flush()
    expect(matrix(el).parentElement).toBe(scroller)
    expect(scroller.scrollTop).toBe(900)
    expect(repSwitches(el).length).toBe(switches.length)
  })

  it('shows the skeleton while there is no matrix yet', async () => {
    let release
    held = new Promise((resolve) => (release = resolve))
    const { el } = mount(AccessControl, { plugins: [createPinia()] })
    await flush()
    expect(matrix(el)).toBeUndefined()
    expect(
      el.querySelector('[aria-label="Loading the surface matrix"]'),
    ).not.toBeNull()
    release()
    await flush()
    expect(matrix(el)).toBeTruthy()
  })
})
