import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from './mount.js'
import { flush, modalStubs, translation } from './stubs.js'
import LeadModal from '@/components/Modals/LeadModal.vue'
import DealModal from '@/components/Modals/DealModal.vue'

// Create raises its busy flag before the Form Script's onBeforeCreate is
// awaited, as DoctypeModal does: a second click while a slow script runs
// must not send a second insert.
const S = vi.hoisted(() => ({ sent: [], gates: [], docs: {} }))

vi.mock('frappe-ui', async (importOriginal) => {
  // enough of a resource to run the create path: validate, then record
  const run = (options, params, temp = {}) => {
    const validate = temp.validate || options.validate
    const refused = validate?.(params)
    if (refused) {
      ;(temp.onError || options.onError)?.(new Error(refused))
      return
    }
    S.sent.push(options.url)
  }
  return {
    ...(await importOriginal()),
    call: vi.fn(),
    toast: { error() {}, success() {}, info() {}, warning() {} },
    createResource: (options) => {
      if (options.auto && options.url.includes('create_deal')) run(options)
      return {
        data: null,
        fetch() {},
        reload() {},
        submit: (params, temp) => run(options, params, temp),
      }
    },
  }
})
vi.mock('reka-ui', async (importOriginal) => {
  const { h } = await import('vue')
  const pass = (name) => ({
    name,
    render() {
      return h('div', this.$slots.default?.())
    },
  })
  return {
    ...(await importOriginal()),
    DialogTitle: pass('DialogTitle'),
    DialogDescription: pass('DialogDescription'),
    VisuallyHidden: pass('VisuallyHidden'),
  }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push() {} }) }))
vi.mock('@/components/FieldLayout/FieldLayout.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/components/EnrichFromWebsite.vue', () => ({
  default: { render: () => null },
}))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    getUser: () => ({ name: 'rep@example.com' }),
    isManager: () => false,
  }),
}))
vi.mock('@/stores/statuses', () => ({
  statusesStore: () => ({
    getLeadStatus: () => ({}),
    getDealStatus: () => ({}),
    statusOptions: () => [{ label: 'Open', value: 'Open' }],
  }),
}))
vi.mock('@/stores/session', () => ({
  sessionStore: () => ({ user: 'rep@example.com' }),
}))
vi.mock('@/composables/onboarding', () => ({
  useCRMOnboarding: () => ({ updateOnboardingStep() {} }),
}))
vi.mock('@framework/ui/telemetry', () => ({
  useTelemetry: () => ({ capture() {} }),
}))
vi.mock('@/data/document', async () => {
  const { reactive } = await import('vue')
  return {
    useDocument: (doctype) => ({
      document: (S.docs[doctype] ||= reactive({ doc: {} })),
      // a Form Script that awaits a call before the record is created
      triggerOnBeforeCreate: () =>
        new Promise((resolve, reject) => S.gates.push({ resolve, reject })),
    }),
  }
})

async function open(component, doctype, values) {
  const w = mount(component, {
    props: { modelValue: true },
    stubs: modalStubs,
    plugins: [translation],
  })
  await flush()
  Object.assign(S.docs[doctype].doc, values)
  return w.vm.$.setupState
}

beforeEach(() => {
  S.sent.length = 0
  S.gates.length = 0
})

describe.each([
  [
    'LeadModal',
    LeadModal,
    'CRM Lead',
    'createNewLead',
    'isLeadCreating',
    { first_name: 'Ann', status: 'New' },
  ],
  [
    'DealModal',
    DealModal,
    'CRM Deal',
    'createDeal',
    'isDealCreating',
    { status: 'Qualification' },
  ],
])('%s create re-entry', (_, component, doctype, create, busy, values) => {
  it('is busy while onBeforeCreate runs and sends one create for two clicks', async () => {
    const m = await open(component, doctype, values)
    m[create]()
    expect(m[busy]).toBe(true)
    m[create]()
    expect(S.gates).toHaveLength(1)
    S.gates.shift().resolve()
    await flush()
    expect(S.sent).toHaveLength(1)
  })

  it('a refused form can be submitted again', async () => {
    const m = await open(component, doctype, { ...values, status: '' })
    m[create]()
    S.gates.shift().resolve()
    await flush()
    expect(m.error).toBe('Status is required')
    expect(m[busy]).toBe(false)
    expect(S.sent).toHaveLength(0)
  })

  it('a script that throws does not leave the button busy', async () => {
    const m = await open(component, doctype, values)
    const attempt = m[create]()
    S.gates.shift().reject(new Error('script failed'))
    await expect(attempt).rejects.toThrow('script failed')
    expect(m[busy]).toBe(false)
  })
})
