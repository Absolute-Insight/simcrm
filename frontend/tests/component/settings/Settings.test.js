/* eslint-disable vue/one-component-per-file, vue/require-default-prop -- stand-ins for frappe-ui controls */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '../mount.js'
import { flush } from './standIns.js'

const backend = vi.hoisted(() => ({ handlers: {}, log: [], toasts: [] }))
vi.mock('frappe-ui', async (importOriginal) => {
  const { defineComponent, h } = await import('vue')
  // v-model:open, as Settings binds it
  const Dialog = defineComponent({
    props: { open: Boolean },
    setup:
      (props, { slots }) =>
      () =>
        props.open
          ? h('div', { 'data-stub': 'Dialog' }, slots.default?.())
          : null,
  })
  const SidebarItem = defineComponent({
    props: { label: String, active: Boolean },
    emits: ['click'],
    setup:
      (props, { emit }) =>
      () =>
        h(
          'button',
          {
            'data-nav': props.label,
            'aria-current': props.active ? 'page' : null,
            onClick: () => emit('click'),
          },
          props.label,
        ),
  })
  return (await import('./standIns.js')).frappeUi(importOriginal, backend, {
    Dialog,
    SidebarItem,
  })
})
// the dialog's accessible title and description need reka-ui's DialogRoot,
// which the stand-in Dialog does not provide
vi.mock('reka-ui', async (importOriginal) => {
  const actual = await importOriginal()
  const { defineComponent } = await import('vue')
  const passthrough = defineComponent({
    setup:
      (_, { slots }) =>
      () =>
        slots.default?.(),
  })
  return {
    ...actual,
    DialogDescription: passthrough,
    DialogTitle: passthrough,
    VisuallyHidden: passthrough,
  }
})
const who = vi.hoisted(() => ({ admin: false }))
vi.mock('@/stores/users', () => ({
  usersStore: () => ({
    isManager: () => true,
    isAdmin: () => who.admin,
    getUser: () => ({ full_name: 'Sam Manager', role: 'Sales Manager' }),
  }),
}))
vi.mock('@/stores/access', () => ({
  accessStore: () => ({ canSee: () => true }),
}))
vi.mock('@/composables/whatsapp', async () => {
  const { ref } = await import('vue')
  return { isWhatsappInstalled: ref(false) }
})
vi.mock('@/composables/leadSyncing', async () => {
  const { ref } = await import('vue')
  return { leadSyncingEnabled: ref(false) }
})
// Every pane is a stand-in that renders its own name: what is under test is
// which one Settings shows, not what the panes do.
const page = vi.hoisted(() => async (name) => {
  const { h } = await import('vue')
  return { default: { name, render: () => h('div', { 'data-page': name }) } }
})
vi.mock('@/components/Settings/Users.vue', () => page('Users'))
vi.mock('@/components/Settings/Hierarchy/Hierarchy.vue', () =>
  page('Hierarchy'),
)
vi.mock('@/components/Settings/Quotas.vue', () => page('Quotas'))
vi.mock('@/components/Settings/VisitTargets.vue', () => page('VisitTargets'))
vi.mock('@/components/Settings/AccessControl.vue', () => page('AccessControl'))
vi.mock('@/components/Settings/AutomationRules.vue', () =>
  page('AutomationRules'),
)
vi.mock('@/components/Settings/AssistantSettings.vue', () =>
  page('AssistantSettings'),
)
vi.mock('@/components/Settings/KnowledgeSettings.vue', () =>
  page('KnowledgeSettings'),
)
vi.mock('@/components/Settings/ReportDigests.vue', () => page('ReportDigests'))
vi.mock('@/components/Settings/InviteUserPage.vue', () =>
  page('InviteUserPage'),
)
vi.mock('@/components/Settings/Profile/ProfilePage.vue', () =>
  page('ProfilePage'),
)
vi.mock('@/components/Settings/PreferencesSettings.vue', () =>
  page('PreferencesSettings'),
)
vi.mock('@/components/Settings/WhatsAppSettings.vue', () =>
  page('WhatsAppSettings'),
)
vi.mock('@/components/Settings/ERPNextSettings.vue', () =>
  page('ERPNextSettings'),
)
vi.mock('@/components/Settings/AcumaticaSettings.vue', () =>
  page('AcumaticaSettings'),
)
vi.mock('@/components/Settings/LeadSyncing/LeadSyncSourcePage.vue', () =>
  page('LeadSyncSourcePage'),
)
vi.mock('@/components/Settings/DefaultsSettings.vue', () =>
  page('DefaultsSettings'),
)
vi.mock('@/components/Settings/BrandSettings.vue', () => page('BrandSettings'))
vi.mock('@/components/Settings/CalendarSettings.vue', () =>
  page('CalendarSettings'),
)
vi.mock('@/components/Settings/HomeActions.vue', () => page('HomeActions'))
vi.mock('@/components/Settings/Forms/FormsSettings.vue', () =>
  page('FormsSettings'),
)
vi.mock('@/components/Settings/GeneralSettings.vue', () =>
  page('GeneralSettings'),
)
vi.mock('@/components/Settings/DashboardSettings.vue', () =>
  page('DashboardSettings'),
)
vi.mock('@/components/Settings/EmailTemplate/EmailTemplatePage.vue', () =>
  page('EmailTemplatePage'),
)
vi.mock('@/components/Settings/Telephony/TelephonyPage.vue', () =>
  page('TelephonyPage'),
)
vi.mock('@/components/Settings/EmailConfig.vue', () => page('EmailConfig'))
vi.mock('@/components/Settings/AssignmentRules/AssignmentRulePage.vue', () =>
  page('AssignmentRulePage'),
)
vi.mock('@/components/Settings/Sla/SlaConfig.vue', () => page('SlaConfig'))

const { showSettings, activeSettingsPage } = await import(
  '@/composables/settings'
)
const { default: Settings } = await import('@/components/Settings/Settings.vue')

const shown = (el) =>
  [...el.querySelectorAll('[data-page]')].map((n) => n.dataset.page)
const nav = (el, label) => el.querySelector(`[data-nav="${label}"]`)

beforeEach(() => {
  backend.toasts.length = 0
  who.admin = false
  showSettings.value = false
  activeSettingsPage.value = ''
})

describe('Settings', () => {
  it('opens a deep-linked page', async () => {
    who.admin = true
    const { el } = mount(Settings)
    await flush()
    showSettings.value = true
    activeSettingsPage.value = 'Templates'
    await flush()
    expect(shown(el)).toEqual(['EmailTemplatePage'])
    expect(backend.toasts).toEqual([])
  })

  it('says so when a deep link names a page this user is not shown', async () => {
    const { el } = mount(Settings)
    await flush()
    showSettings.value = true
    activeSettingsPage.value = 'Templates'
    await flush()
    expect(shown(el)).toEqual(['ProfilePage'])
    expect(backend.toasts).toEqual([
      ['warning', 'You do not have access to Templates.'],
    ])
  })

  it('keeps the open page across a remount, and opens it again on a click', async () => {
    const first = mount(Settings)
    await flush()
    showSettings.value = true
    await flush()
    nav(first.el, 'Sales Targets').click()
    await flush()
    expect(shown(first.el)).toEqual(['Quotas'])

    // the viewport crosses md: one layout's <Settings/> goes, the other's comes
    first.unmount()
    const second = mount(Settings)
    await flush()
    expect(shown(second.el)).toEqual(['Quotas'])

    nav(second.el, 'Profile').click()
    await flush()
    nav(second.el, 'Sales Targets').click()
    await flush()
    expect(shown(second.el)).toEqual(['Quotas'])
  })

  it('opens a page clicked in a fresh instance whose page was already chosen', async () => {
    showSettings.value = true
    activeSettingsPage.value = 'Sales Targets'
    const { el } = mount(Settings)
    await flush()
    nav(el, 'Sales Targets').click()
    await flush()
    expect(shown(el)).toEqual(['Quotas'])
  })
})
