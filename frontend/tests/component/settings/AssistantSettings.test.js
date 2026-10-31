import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '../mount.js'
import { enter, field, flush } from './standIns.js'

const backend = vi.hoisted(() => ({ handlers: {}, log: [], toasts: [] }))
vi.mock('frappe-ui', async (importOriginal) =>
  (await import('./standIns.js')).frappeUi(importOriginal, backend),
)

const { default: AssistantSettings } = await import(
  '@/components/Settings/AssistantSettings.vue'
)

const SETTINGS = {
  enabled: 1,
  base_url: 'http://llm:8080/v1',
  model: 'minicpm',
  timeout: 50,
  max_tokens: 800,
  reasoning_off: 0,
  daily_call_budget: 0,
  assistant_reads_products: 0,
  analyst_enabled: 1,
  signals_enabled: 1,
  idle_deal_days: 14,
  close_horizon_days: 14,
  suggestion_ttl_days: 7,
  dismiss_cooldown_days: 30,
  max_open_per_user: 20,
}

beforeEach(() => {
  backend.log.length = 0
  backend.handlers = {
    'crm.agent.api.get_settings': () => ({ ...SETTINGS }),
    'crm.api.suggestions.get_dismissal_stats': () => [],
    'frappe.client.set_value': ({ name }) => ({ name }),
  }
})

describe('AssistantSettings', () => {
  it('a saved form is clean: Test connection opens and Save closes', async () => {
    const { el } = mount(AssistantSettings)
    await flush()
    const state = () => ({
      testDisabled: field(el, 'Test connection').disabled,
      saveDisabled: field(el, 'Save').disabled,
      hint: el.textContent.includes('Save your changes first'),
    })
    expect(state()).toEqual({
      testDisabled: false,
      saveDisabled: true,
      hint: false,
    })

    await enter(el, 'Model', 'minicpm-v4')
    expect(state()).toEqual({
      testDisabled: true,
      saveDisabled: false,
      hint: true,
    })

    field(el, 'Save').click()
    await flush()
    const sent = backend.log.find((r) => r.url === 'frappe.client.set_value')
    expect(sent.params.fieldname.model).toBe('minicpm-v4')
    expect(el.textContent).toContain('Saved.')
    expect(state()).toEqual({
      testDisabled: false,
      saveDisabled: true,
      hint: false,
    })

    // and a further edit is dirty against what was just saved
    await enter(el, 'Model', 'minicpm')
    expect(state().saveDisabled).toBe(false)
  })
})
