import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'

// frappe-ui's real document resource, wired to an in-memory backend through its
// own `resourceFetcher` hook: the bugs below live in how that resource treats
// the doc a whitelisted method sends back, so a stand-in would hide them.
const backend = vi.hoisted(() => ({ handlers: {}, log: [] }))

vi.mock('frappe-ui', async (importOriginal) => {
  const actual = await importOriginal()
  const dispatch = async (url, params = {}) => {
    backend.log.push({ url, params })
    const key =
      url === 'run_doc_method' ? `run_doc_method:${params.method}` : url
    const handler = backend.handlers[key]
    if (!handler) throw new Error(`no fake handler for ${key}`)
    return handler(params)
  }
  actual.setConfig('resourceFetcher', (opts) => dispatch(opts.url, opts.params))
  actual.setConfig('fallbackErrorHandler', () => {})
  return {
    ...actual,
    call: dispatch,
    toast: { success: () => {}, error: () => {}, info: () => {} },
  }
})
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog: () => {}, $socket: { on() {}, off() {} } }),
}))
vi.mock('@/stores/help', () => ({ openHelpCenter: () => {} }))
vi.mock('@/components/Controls/Link.vue', () => ({
  default: { render: () => null },
}))

const SAVED = {
  doctype: 'ERPNext CRM Settings',
  name: 'ERPNext CRM Settings',
  enabled: 1,
  is_erpnext_in_different_site: 0,
  erpnext_company: 'MBP Engineering',
  create_customer_on_status_change: 0,
  deal_status: null,
  sync_products: 0,
  sync_issues: [],
}
// run_doc_method answers with the saved document beside the method's own value
const withDocs = (message) => () => ({ docs: [{ ...SAVED }], message })

function failure(message) {
  const error = new Error(message)
  error.messages = [message]
  return error
}

const settled = () => new Promise((resolve) => setTimeout(resolve, 0))
async function flush(rounds = 10) {
  for (let i = 0; i < rounds; i++) await settled()
}

const buttonNamed = (el, text) =>
  [...el.querySelectorAll('button')].find((b) => b.textContent.trim() === text)

function autoCreateSwitch(el) {
  const label = [...el.querySelectorAll('div')].find(
    (d) => d.textContent.trim() === 'Auto Create Customer',
  )
  return label
    .closest('.flex.items-center.justify-between')
    .querySelector('[role="switch"]')
}

const gets = () =>
  backend.log.filter((r) => r.url === 'frappe.client.get').length

const { default: ERPNextSettings } = await import(
  '@/components/Settings/ERPNextSettings.vue'
)

beforeEach(() => {
  backend.log.length = 0
  backend.handlers = {
    'frappe.client.get': () => ({ ...SAVED }),
    'run_doc_method:is_erpnext_installed': withDocs(true),
    'run_doc_method:run_product_sync': withDocs(null),
    'crm.fcrm.doctype.erpnext_crm_settings.erpnext_crm_settings.get_product_sync_status':
      () => ({
        products: { count: 0, rows: [] },
        items: { count: 0, rows: [] },
        failed: [],
        unsynced: { items: 0, products: 0, sync_products: false },
      }),
  }
})

async function mountSettings() {
  const w = mount(ERPNextSettings)
  await flush()
  return w
}

describe('ERPNextSettings', () => {
  // First: frappe-ui caches a document resource per doctype for the life of
  // the module, and this one needs to meet it fresh.
  it('shows an error with a retry when the settings cannot be loaded, and loads them once', async () => {
    backend.handlers['frappe.client.get'] = () => {
      throw failure('502 Bad Gateway')
    }
    const { el } = await mountSettings()

    // one request per mount: the resource's own auto-fetch doubled the one
    // onMounted sends
    expect(gets()).toBe(1)
    expect(el.querySelector('[role="alert"]')).toBeTruthy()
    expect(el.querySelector('.mt-\\[35\\%\\]')).toBeNull()

    backend.handlers['frappe.client.get'] = () => ({ ...SAVED })
    buttonNamed(el, 'Try again').click()
    await flush()

    expect(gets()).toBe(2)
    expect(el.querySelector('[role="alert"]')).toBeNull()
    expect(buttonNamed(el, 'Sync Now')).toBeTruthy()
  })

  it('keeps an unsaved edit when Sync Now runs', async () => {
    // A document method's answer carries the saved doc, and the resource puts
    // it in place of the one on screen: the toggle the admin had just switched
    // on went back off, and Update no longer offered to save it.
    const { el } = await mountSettings()
    autoCreateSwitch(el).click()
    await flush()
    expect(autoCreateSwitch(el).getAttribute('aria-checked')).toBe('true')

    buttonNamed(el, 'Sync Now').click()
    await flush()

    expect(
      backend.log.some((r) => r.params?.method === 'run_product_sync'),
    ).toBe(true)
    expect(autoCreateSwitch(el).getAttribute('aria-checked')).toBe('true')
    expect(buttonNamed(el, 'Update').disabled).toBe(false)
  })

  it('keeps an unsaved edit when the company list is refreshed', async () => {
    const remote = {
      ...SAVED,
      is_erpnext_in_different_site: 1,
      erpnext_site_url: 'https://erp.example.com',
      api_key: 'key',
      api_secret: 'secret',
    }
    const answer = (message) => () => ({ docs: [{ ...remote }], message })
    backend.handlers['frappe.client.get'] = () => ({ ...remote })
    backend.handlers['run_doc_method:is_erpnext_installed'] = answer(false)
    backend.handlers['run_doc_method:get_external_companies'] = answer([
      { company_name: 'MBP Engineering' },
    ])
    const { el } = await mountSettings()
    autoCreateSwitch(el).click()
    await flush()

    // the Combobox footer's button, rendered once the list is open
    el.querySelector('[aria-haspopup]').click()
    await flush()
    const refresh = buttonNamed(document.body, 'Refresh Companies')
    const before = backend.log.length
    refresh.click()
    await flush()

    expect(
      backend.log
        .slice(before)
        .some((r) => r.params?.method === 'get_external_companies'),
    ).toBe(true)
    expect(autoCreateSwitch(el).getAttribute('aria-checked')).toBe('true')
  })
})
