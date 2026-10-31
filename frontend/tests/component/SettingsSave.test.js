import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'
import { mount } from './mount.js'

/**
 * Every FCRM Settings pane saves through one document resource, which
 * stores/settings.js creates at boot (SidebarBrand imports it) with no
 * setValue handlers. frappe-ui hands that cached resource to every later
 * caller and ignores their options, so useDocument's and Hierarchy's own
 * onError never attached and the panes passed none: a refused save showed
 * nothing at all, and `:loading="settings.loading"` read a property document
 * resources do not have. Real stores/settings.js, useDocument and frappe-ui
 * document resources here; only the server and the leaf controls are faked.
 */
const { toast, dialogs } = vi.hoisted(() => ({
  toast: { error: vi.fn(), success: vi.fn() },
  dialogs: [],
}))
vi.mock('frappe-ui', async () => {
  const { createResource } = await import(
    '../../node_modules/frappe-ui/src/resources/resources.js'
  )
  const { createDocumentResource } = await import(
    '../../node_modules/frappe-ui/src/resources/documentResource.js'
  )
  const { setConfig } = await import(
    '../../node_modules/frappe-ui/src/utils/config.ts'
  )
  const { h } = await import('vue')
  return {
    createResource,
    createDocumentResource,
    setConfig,
    call: async () => null,
    toast,
    ErrorMessage: {
      props: ['message'],
      render() {
        return this.message
          ? h('p', { class: 'inline-error' }, this.message)
          : null
      },
    },
    FormControl: { render: () => null },
  }
})
const stub = { default: { render: () => null } }
vi.mock('@/components/Controls/Grid.vue', () => stub)
vi.mock('@/components/Controls/ImageUploader.vue', () => stub)
// The currency picker: a click picks ZAR, as the real one emits on a choice.
vi.mock('@/components/Controls/Link.vue', async () => {
  const { h } = await import('vue')
  return {
    default: {
      emits: ['change'],
      setup:
        (_, { emit }) =>
        () =>
          h('button', {
            class: 'pick-currency',
            onClick: () => emit('change', 'ZAR'),
          }),
    },
  }
})
// The toggle: a click flips it, as the real one emits on a change.
vi.mock('@/components/ui/CheckSwitch.vue', async () => {
  const { h } = await import('vue')
  return {
    default: {
      props: ['modelValue'],
      emits: ['update:modelValue'],
      setup:
        (props, { emit }) =>
        () =>
          h('button', {
            class: 'check-switch',
            onClick: () => emit('update:modelValue', !props.modelValue),
          }),
    },
  }
})
// VisitTargets' gate on who may flip its lock
vi.mock('@/stores/session', () => ({ sessionStore: () => ({ user: 'm@x' }) }))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({ isManager: () => true, isAdmin: () => false }),
}))
vi.mock('vue-router', () => ({ useRoute: () => ({ name: 'Dashboard' }) }))
vi.mock('@/stores/global', () => ({
  globalStore: () => ({ $dialog: (options) => dialogs.push(options) }),
}))
// useDocument's unrelated dependencies
vi.mock('@/data/script', () => ({
  getScript: () => ({ setupScript: async () => [], scripts: {} }),
}))
vi.mock('@/stores/meta', () => ({ getMeta: () => ({}) }))
vi.mock('@/composables/useAttachments', () => ({
  useAttachments: () => ({ trackOldFile() {}, processPendingDeletions() {} }),
}))
vi.mock('@/composables/settings', async () => {
  const { ref } = await import('vue')
  return { showSettings: ref(true), activeSettingsPage: ref('') }
})
vi.mock('@/utils', () => ({
  runSequentially: async () => {},
  parseAssignees: (d) => d,
  sanitizeText: (t) => t,
}))
vi.mock('@/utils/fieldTransforms', () => ({ findMissingMandatory: () => [] }))
vi.mock('@/utils/newDocument', () => ({ newDocumentDraft: () => ({}) }))

import { setConfig } from 'frappe-ui'

const SETTINGS = {
  doctype: 'FCRM Settings',
  name: 'FCRM Settings',
  brand_name: 'Vectora',
  currency: '',
  dropdown_items: [{ name: 'r1', name1: 'kanban_view', is_standard: 1 }],
}

let setValue // what the server does with a frappe.client.set_value
function refuse(message, exc_type = 'ValidationError') {
  return () => {
    const error = new Error(`/api/method/frappe.client.set_value ${exc_type}`)
    error.exc_type = exc_type
    error.status = 417
    error.messages = [message]
    throw error
  }
}

const flush = async () => {
  for (let i = 0; i < 4; i++) {
    await new Promise((r) => setTimeout(r, 0))
    await nextTick()
  }
}

/** The global Button, reporting the props the panes give it. */
const Button = {
  props: ['label', 'loading'],
  setup(props, { attrs }) {
    return () =>
      h('button', {
        'data-label': props.label,
        'data-loading': String(Boolean(props.loading)),
        onClick: attrs.onClick,
      })
  },
}
const update = (el) => el.querySelector('button[data-label="Update"]')

setConfig('resourceFetcher', async ({ url, params }) => {
  if (url === 'frappe.client.get') return structuredClone(SETTINGS)
  if (url === 'frappe.client.set_value') return setValue(params)
  return null
})

// app start: SidebarBrand imports the store before any pane opens
const { _settings: settings } = (
  await import('@/stores/settings')
).getSettings()

// Imported here, once, not in the tests: each pane reaches the whole Phosphor
// barrel, seconds of cold transform on a CI runner. Inside a test that counts
// against its 5s limit, and a test that times out keeps running, so its late
// toast lands in the next test's count.
const { default: BrandSettings } = await import(
  '@/components/Settings/BrandSettings.vue'
)
const { default: HomeActions } = await import(
  '@/components/Settings/HomeActions.vue'
)
const { default: VisitTargets } = await import(
  '@/components/Settings/VisitTargets.vue'
)
const { default: DashboardSettings } = await import(
  '@/components/Settings/DashboardSettings.vue'
)

beforeAll(flush)

beforeEach(async () => {
  toast.error.mockClear()
  toast.success.mockClear()
  vi.spyOn(console, 'error').mockImplementation(() => {})
  dialogs.length = 0
  await settings.reload()
})

describe('a refused FCRM Settings save', () => {
  it('Brand: says why', async () => {
    setValue = refuse('Brand name is too long')
    const { el } = mount(BrandSettings, { stubs: { Button } })
    settings.doc.brand_name = 'Vectora Africa (Pty) Ltd'
    await flush()
    update(el).click()
    await flush()
    expect(toast.error).toHaveBeenCalledWith('Brand name is too long')
  })

  it('Home Actions: says why, through useDocument', async () => {
    setValue = refuse('Cannot delete standard items kanban_view')
    const { el } = mount(HomeActions, { stubs: { Button } })
    await flush()
    settings.doc.dropdown_items = []
    await flush()
    update(el).click()
    await flush()
    expect(toast.error).toHaveBeenCalledWith(
      'Cannot delete standard items kanban_view',
    )
  })

  it('Hierarchy toggle: says why', async () => {
    // Hierarchy.vue asks for the same resource with an onError of its own,
    // which the cache drops; its toggle is a setValue on the store's.
    setValue = refuse('Only a System Manager can change this')
    const { createDocumentResource } = await import('frappe-ui')
    const fromHierarchy = createDocumentResource({
      doctype: 'FCRM Settings',
      name: 'FCRM Settings',
      auto: true,
    })
    expect(fromHierarchy).toBe(settings)
    await fromHierarchy.setValue
      .submit({ enable_sales_hierarchy: 1 })
      .catch(() => {})
    expect(toast.error).toHaveBeenCalledWith(
      'Only a System Manager can change this',
    )
  })

  it('Visit Targets lock: says why, once', async () => {
    // setLock awaits the store's setValue, whose onError already toasts;
    // a second toast of its own read the refusal out twice.
    setValue = refuse('Insufficient Permission for FCRM Settings')
    const { el } = mount(VisitTargets)
    await flush()
    el.querySelector('.check-switch').click()
    await flush()
    expect(toast.error).toHaveBeenCalledOnce()
    expect(toast.error).toHaveBeenCalledWith(
      'Insufficient Permission for FCRM Settings',
    )
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('falls back to a sentence of its own when the server wrote none', async () => {
    setValue = () => {
      const error = new Error('/api/method/frappe.client.set_value')
      error.status = 500
      error.messages = ['Internal Server Error']
      throw error
    }
    settings.doc.brand_name = 'x'
    await settings.save.submit().catch(() => {})
    expect(toast.error).toHaveBeenCalledWith('Could not save the settings.')
  })
})

describe('an FCRM Settings save in flight', () => {
  it('shows the Update button as busy', async () => {
    let finish
    setValue = (params) =>
      new Promise(
        (r) => (finish = () => r({ ...SETTINGS, ...params.fieldname })),
      )
    const { el } = mount(BrandSettings, { stubs: { Button } })
    settings.doc.brand_name = 'Vectora Africa'
    await flush()
    update(el).click()
    await flush()
    expect(update(el).dataset.loading).toBe('true')
    finish()
    await flush()
  })
})

describe('Dashboard settings', () => {
  const mountDashboard = () => mount(DashboardSettings, { stubs: { Button } })

  it('reports a missing currency once, inline, without saving', async () => {
    setValue = vi.fn(() => SETTINGS)
    const { el } = mountDashboard()
    settings.doc.enable_forecasting = 1
    await flush()
    update(el).click()
    await flush()
    expect(el.querySelector('.inline-error')?.textContent).toBe(
      'Please select a currency before saving.',
    )
    expect(toast.error).not.toHaveBeenCalled()
    expect(setValue).not.toHaveBeenCalled()
  })

  it('a refused currency is not left showing as set', async () => {
    // "Once set, cannot be edited": a currency shown as set hides the picker,
    // so a failed save that left it on screen left no way to try again.
    setValue = refuse('Currency cannot be changed')
    const { el } = mountDashboard()
    await flush()
    el.querySelector('.pick-currency').click()
    const close = vi.fn()
    dialogs.at(-1).actions[0].onClick({ close })
    await flush()

    expect(toast.error).toHaveBeenCalledWith('Currency cannot be changed')
    expect(settings.doc.currency).toBe('')
    expect(el.querySelector('.pick-currency')).not.toBeNull()
  })

  it('a currency the server accepts is shown as set', async () => {
    setValue = (params) => ({ ...SETTINGS, ...params.fieldname })
    const { el } = mountDashboard()
    await flush()
    el.querySelector('.pick-currency').click()
    const close = vi.fn()
    dialogs.at(-1).actions[0].onClick({ close })
    await flush()

    expect(settings.doc.currency).toBe('ZAR')
    expect(close).toHaveBeenCalledOnce()
  })
})
