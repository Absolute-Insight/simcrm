import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// The server's copy of the settings, and what the pane asked of the backend.
const backend = vi.hoisted(() => ({ calls: [], issues: [], reloads: 0 }))
const SERVER = {
  enabled: 1,
  instance_url: 'https://erp.example.com',
  salesperson_owners: '{\n "JDOE": "jdoe@example.com"\n}',
  salesperson_branches: '',
}

vi.mock('frappe-ui', async (importOriginal) => {
  const { reactive } = await import('vue')
  return {
    ...(await importOriginal()),
    call: async (method) => {
      backend.calls.push(method)
      if (method.endsWith('.get_sync_status')) {
        return {
          last_synced_at: '2026-10-30 00:00:00',
          open_issues: backend.issues.length,
          running: false,
          last_sync_error: '',
          pending_retries: 0,
        }
      }
      if (method.endsWith('.get_open_sync_issues')) return backend.issues
      if (method.endsWith('.dismiss_sync_issue')) return {}
      if (method.endsWith('.link_existing_customer')) return {}
      throw new Error(`unexpected call ${method}`)
    },
    toast: { success: () => {}, error: () => {}, info: () => {} },
    // What frappe-ui's document resource does on reload: the server copy replaces
    // both the doc on screen and the copy edits are compared against.
    createDocumentResource: () => {
      const resource = reactive({
        doc: { ...SERVER },
        originalDoc: { ...SERVER },
        get: { error: null },
        save: { loading: false, submit: async () => {} },
        reload: async () => {
          backend.reloads += 1
          resource.doc = { ...SERVER }
          resource.originalDoc = { ...SERVER }
        },
      })
      return resource
    },
  }
})
vi.mock('@/components/Controls/Link.vue', () => ({
  default: { render: () => null },
}))

const { default: AcumaticaSettings } = await import(
  '@/components/Settings/AcumaticaSettings.vue'
)

const settle = async () => {
  for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0))
}
const button = (el, label) =>
  [...el.querySelectorAll('button')].find((b) => b.textContent.trim() === label)
const input = (el, placeholder) =>
  [...el.querySelectorAll('input')].find((i) => i.placeholder === placeholder)
const type = async (field, value) => {
  field.value = value
  field.dispatchEvent(new Event('input', { bubbles: true }))
  await settle()
}

const INSTANCE = 'https://tenant.acumatica.com'
const TYPED = 'https://typed-but-unsaved.example.com'

describe('AcumaticaSettings unsaved edits', () => {
  beforeEach(() => {
    backend.calls.length = 0
    backend.reloads = 0
    backend.issues = [
      {
        name: 'I1',
        entity: 'Customer',
        remote_id: 'ACME',
        kind: 'Possible Duplicate',
        detail: 'looks like ACME01',
        detected_on: '2026-11-01 10:00:00',
        candidates: [{ customer_id: 'ACME01', organization_name: 'Acme' }],
      },
    ]
  })

  it('survive dismissing a sync issue', async () => {
    // Dismiss reloads the settings document; the reload used to replace the form
    // with the server copy, so a typed instance URL snapped back with no notice.
    const w = mount(AcumaticaSettings)
    await settle()
    await type(input(w.el, INSTANCE), TYPED)

    button(w.el, 'Dismiss').click()
    await settle()

    expect(backend.calls.some((m) => m.endsWith('.dismiss_sync_issue'))).toBe(
      true,
    )
    expect(backend.reloads).toBe(1)
    expect(input(w.el, INSTANCE).value).toBe(TYPED)
  })

  it('survive linking a customer, the salesperson rows included', async () => {
    const w = mount(AcumaticaSettings)
    await settle()
    await type(input(w.el, INSTANCE), TYPED)
    await type(input(w.el, 'Salesperson ID'), 'ASMITH')
    await type(input(w.el, 'Quote branch'), 'CPT')

    button(w.el, 'Link to ACME01').click()
    await settle()

    expect(backend.reloads).toBe(1)
    expect(input(w.el, INSTANCE).value).toBe(TYPED)
    // the rows on screen and the JSON a Save would send still agree
    expect(input(w.el, 'Salesperson ID').value).toBe('ASMITH')
    expect(input(w.el, 'Quote branch').value).toBe('CPT')
  })

  it('still takes the server copy for a field nobody edited', async () => {
    const w = mount(AcumaticaSettings)
    await settle()
    SERVER.instance_url = 'https://moved.example.com'
    try {
      button(w.el, 'Dismiss').click()
      await settle()
      expect(input(w.el, INSTANCE).value).toBe('https://moved.example.com')
    } finally {
      SERVER.instance_url = 'https://erp.example.com'
    }
  })
})
