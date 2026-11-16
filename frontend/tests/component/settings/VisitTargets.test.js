import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { mount } from '../mount.js'
import { flush } from './standIns.js'

const backend = vi.hoisted(() => ({ handlers: {}, log: [], toasts: [] }))
vi.mock('frappe-ui', async (importOriginal) =>
  (await import('./standIns.js')).frappeUi(importOriginal, backend),
)
const session = vi.hoisted(() => ({ manager: true }))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    isManager: () => session.manager,
    isAdmin: () => false,
  }),
}))
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: 'mgr@x.test' }),
}))

/* FCRM Settings as the pane sees it: a doc, and a setValue that writes it */
const settings = vi.hoisted(() => ({ doc: null, setValue: null, saved: [] }))
vi.mock('@/stores/settings', () => ({
  getSettings: () => ({ _settings: settings }),
}))

const { default: VisitTargets } = await import(
  '@/components/Settings/VisitTargets.vue'
)

const grace = (el) => el.querySelector('#offline-grace-hours')
function enter(input, text) {
  input.value = text
  input.dispatchEvent(new FocusEvent('blur'))
}

beforeEach(() => {
  backend.log.length = 0
  backend.toasts.length = 0
  backend.handlers = { 'crm.api.visit_targets.get_visit_targets': () => [] }
  settings.saved = []
  session.manager = true
  settings.doc = reactive({ lock_past_plans: 1, offline_grace_hours: 24 })
  settings.setValue = reactive({
    loading: false,
    submit: async (values) => {
      settings.saved.push(values)
      Object.assign(settings.doc, values)
    },
  })
})

describe('Visit Targets, offline capture grace', () => {
  it('shows the window beside the day lock, and saves a new one', async () => {
    const { el } = mount(VisitTargets)
    await flush()
    expect(el.textContent).toContain('Offline capture grace (hours)')
    expect(grace(el).value).toBe('24')

    enter(grace(el), '36')
    await flush()
    expect(settings.saved).toEqual([{ offline_grace_hours: 36 }])
  })

  it('reads an unset window as the default day', async () => {
    settings.doc.offline_grace_hours = null
    const { el } = mount(VisitTargets)
    await flush()
    expect(grace(el).value).toBe('24')
  })

  it('refuses a window outside 1 to 168 hours without saving it', async () => {
    const { el } = mount(VisitTargets)
    await flush()
    for (const text of ['0', '-3', '1.5', '', '169']) {
      enter(grace(el), text)
      await flush()
      expect(grace(el).value).toBe('24')
    }
    expect(settings.saved).toEqual([])
    expect(backend.toasts.filter(([kind]) => kind === 'error')).toHaveLength(5)
  })

  it('is not offered while past days are open', async () => {
    settings.doc.lock_past_plans = 0
    const { el } = mount(VisitTargets)
    await flush()
    expect(grace(el)).toBeNull()
  })

  it('is not offered to a rep', async () => {
    session.manager = false
    const { el } = mount(VisitTargets)
    await flush()
    expect(grace(el)).toBeNull()
    expect(el.textContent).not.toContain('Offline capture grace')
  })
})
