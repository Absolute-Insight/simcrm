import { beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { setConfig } from 'frappe-ui'
import { mount } from './mount.js'

// A save that useDocument blocks before it is sent -- a Form Script's
// onValidate throws, or a mandatory field is empty -- must still reach the
// caller's per-submit onError: that is where updateField puts the edited
// value back. Through the real useDocument and frappe-ui's real resources.
const S = vi.hoisted(() => ({ controllers: [], requests: [], toasts: [] }))

vi.mock('@/data/script', () => ({
  getScript: () => ({
    setupScript: async () => S.controllers,
    scripts: { data: [] },
  }),
}))
vi.mock('@/stores/global', () => ({ globalStore: () => ({}) }))
vi.mock('@/stores/meta', () => ({
  getMeta: () => ({
    getFields: () => [],
    doctypesMeta: {
      'CRM Lead': {
        fields: [
          { fieldname: 'first_name', label: 'First Name', reqd: 1 },
          { fieldname: 'website', label: 'Website' },
        ],
      },
    },
  }),
}))
vi.mock('@/composables/useAttachments', () => ({
  useAttachments: () => ({
    trackOldFile() {},
    processPendingDeletions() {},
  }),
}))
vi.mock('frappe-ui', async (importOriginal) => ({
  ...(await importOriginal()),
  toast: { error: (m) => S.toasts.push(m), success() {} },
}))

const { useDocument } = await import('@/data/document')

const settle = () => new Promise((r) => setTimeout(r, 20))

async function openLead(name, doc) {
  setConfig('resourceFetcher', async ({ url, params }) => {
    S.requests.push(url)
    if (url === 'frappe.client.get') return { name, ...doc }
    if (url === 'frappe.client.set_value') return { name, ...params.fieldname }
    return null
  })
  let document
  mount({
    setup() {
      ;({ document } = useDocument('CRM Lead', name))
      return () => h('div')
    },
  })
  await settle()
  return document
}

function submit(document) {
  const outcome = { error: null, success: false }
  document.save.submit(null, {
    onSuccess: () => (outcome.success = true),
    onError: (e) => (outcome.error = e),
  })
  return outcome
}

beforeEach(() => {
  S.controllers = []
  S.requests.length = 0
  S.toasts.length = 0
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

describe('a save useDocument blocks before sending it', () => {
  it('reaches onError when a mandatory field is empty', async () => {
    const document = await openLead('CRM-LEAD-BLOCK-1', { first_name: 'Ann' })
    document.doc.first_name = ''
    const outcome = submit(document)
    await settle()

    expect(S.requests).not.toContain('frappe.client.set_value')
    expect(outcome.success).toBe(false)
    expect(outcome.error?.messages).toEqual([
      'Mandatory fields required: First Name',
    ])
  })

  it("reaches onError when the form script's onValidate throws", async () => {
    S.controllers = [
      {
        _className: 'CRMLead',
        onValidate() {
          throw new Error('Website must start with https://')
        },
      },
    ]
    const document = await openLead('CRM-LEAD-BLOCK-2', { first_name: 'Ann' })
    document.doc.website = 'example.com'
    const outcome = submit(document)
    await settle()

    expect(S.requests).not.toContain('frappe.client.set_value')
    expect(outcome.error?.messages).toEqual([
      'Website must start with https://',
    ])
    // reported once, as before
    expect(S.toasts).toEqual(['Website must start with https://'])
  })

  it('still sends a save nothing blocks', async () => {
    const document = await openLead('CRM-LEAD-BLOCK-3', { first_name: 'Ann' })
    document.doc.website = 'https://example.com'
    const outcome = submit(document)
    await settle()

    expect(S.requests).toContain('frappe.client.set_value')
    expect(outcome.error).toBe(null)
  })
})
